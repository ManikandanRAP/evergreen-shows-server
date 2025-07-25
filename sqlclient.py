import pymysql
import os
import json
from auth import get_password_hash
from contextlib import contextmanager
from pydantic import BaseModel
from fastapi import Request
from fastapi.exceptions import RequestValidationError

# --- Configuration ---
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpassword")
DB_NAME = os.environ.get("DB_NAME", "evergreen")

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("Validation error:", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@contextmanager
def get_db_connection():
    connection = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        yield connection
    finally:
        connection.close()

class SqlClient:
    def _execute_query(self, query: str, params: tuple = None, fetch: str = None, is_transaction=False):
        """Common function to execute SQL queries."""
        try:
            with get_db_connection() as db:
                with db.cursor() as cursor:
                    rows_affected = cursor.execute(query, params)
                    if fetch == 'one':
                        result = cursor.fetchone()
                    elif fetch == 'all':
                        result = cursor.fetchall()
                    else:
                        result = None
                    
                    if is_transaction:
                        db.commit()
                    
                    return result, rows_affected, None
        except pymysql.Error as e:
            # In a real app, you'd want to log this error.
            return None, 0, e

    def get_all_podcasts(self):
        sql = "SELECT * FROM shows"
        shows, _, error = self._execute_query(sql, fetch='all')
        if error:
            return []
        return shows

    def get_podcast_by_id(self, show_id: str):
        sql = "SELECT * FROM shows WHERE id = %s"
        show, _, error = self._execute_query(sql, (show_id,), fetch='one')
        if error:
            return None, str(error)
        return show, None

    def filter_podcasts(self, filters: dict):
        query = "SELECT * FROM shows"
        where_clauses = []
        values = []

        for key, value in filters.items():
            if value is not None:
                # For boolean values, SQL expects 1 or 0
                if isinstance(value, bool):
                    value = 1 if value else 0
                where_clauses.append(f"`{key}` = %s")
                values.append(value)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        results, _, error = self._execute_query(query, tuple(values), fetch='all')
        if error:
            return None, error
        return results, None

    def delete_user(self, user_id: str):
        # First, delete any associations this user has with shows to maintain referential integrity.
        unassociate_sql = "DELETE FROM show_partners WHERE partner_id = %s"
        self._execute_query(unassociate_sql, (user_id,), is_transaction=True)
        # We don't check for errors here, as the user may not have any associations.

        # Then, delete the user.
        delete_sql = "DELETE FROM users WHERE id = %s"
        rows_affected, _, error = self._execute_query(delete_sql, (user_id,), is_transaction=True)
        if error:
            return False, str(error)
        if rows_affected == 0:
            return False, "User not found"
        return True, None

    def unassociate_partner_from_show(self, show_id: str, partner_id: str):
        sql = "DELETE FROM show_partners WHERE show_id = %s AND partner_id = %s"
        rows_affected, _, error = self._execute_query(sql, (show_id, partner_id), is_transaction=True)
        if error:
            return False, str(error)
        if rows_affected == 0:
            return False, "Association not found"
        return True, None

    def update_podcast(self, show_id: str, show_data: BaseModel):
        # Pydantic's exclude_unset=True can be tricky. A more robust check is needed.
        # We check if any of the fields in the model have been set by the client.
        if not show_data.model_fields_set:
            return None, "No update data provided"
        
        update_data = show_data.model_dump(exclude_unset=True)

        set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
        sql_update = f"UPDATE shows SET {set_clause} WHERE id = %s"
        values = list(update_data.values()) + [show_id]

        _, rows_affected, error = self._execute_query(sql_update, tuple(values), is_transaction=True)
        if error:
            return None, str(error)
        if rows_affected == 0:
            return None, f"Podcast with id {show_id} not found"

        sql_select = "SELECT * FROM shows WHERE id = %s"
        updated_show, _, error = self._execute_query(sql_select, (show_id,), fetch='one')
        return updated_show, str(error) if error else None

    def delete_podcast(self, show_id: str):
        # sql = "DELETE FROM demographic WHERE show_id = %s"
        # _, rows_affected, error = self._execute_query(sql, (show_id,), is_transaction=True)
        # if error:
        #     return False, str(error)
        # if rows_affected == 0:
        #     return False, f"Podcast with id {show_id} not found"

        
        sql = "DELETE FROM shows WHERE id = %s"
        _, rows_affected, error = self._execute_query(sql, (show_id,), is_transaction=True)
        if error:
            return False, str(error)
        if rows_affected == 0:
            return False, f"Podcast with id {show_id} not found"
        return True, None

    def update_password(self, user_id: str, new_password: str):
        password_hash = get_password_hash(new_password)
        sql = "UPDATE users SET password_hash = %s WHERE id = %s"
        _, rows_affected, error = self._execute_query(sql, (password_hash, user_id), is_transaction=True)
        if error:
            return False, str(error)
        if rows_affected == 0:
            return False, f"User with id {user_id} not found"
        return True, None

    def get_user_by_email(self, email: str):
        sql = "SELECT * FROM users WHERE email = %s"
        user, _, error = self._execute_query(sql, (email,), fetch='one')
        return user, error

    def get_user_by_id(self, user_id: str):
        sql = "SELECT * FROM users WHERE id = %s"
        user, _, error = self._execute_query(sql, (user_id,), fetch='one')
        return user, error

    def create_partner(self, partner_data):
        user_id = os.urandom(16).hex()
        password_hash = get_password_hash(partner_data.password)
        partner_id = os.urandom(16).hex()

        sql_user = "INSERT INTO users (id, name, email, password_hash, role) VALUES (%s, %s, %s, %s, 'partner')"
        sql_partner = "INSERT INTO partners (id, user_id) VALUES (%s, %s)"
        sql_select = "SELECT * FROM users WHERE id = %s"

        try:
            with get_db_connection() as db:
                with db.cursor() as cursor:
                    cursor.execute(sql_user, (user_id, partner_data.name, partner_data.email, password_hash))
                    cursor.execute(sql_partner, (partner_id, user_id))
                    db.commit()
                    cursor.execute(sql_select, (user_id,))
                    new_user = cursor.fetchone()
                    return new_user, None
        except pymysql.IntegrityError:
            return None, f"Partner with email {partner_data.email} already exists."
        except pymysql.Error as e:
            return None, str(e)

    def associate_partner_with_show(self, show_id: str, partner_id: str):
        association_id = os.urandom(16).hex()
        sql = "INSERT INTO show_partners (id, show_id, partner_id) VALUES (%s, %s, %s)"
        
        _, _, error = self._execute_query(sql, (association_id, show_id, partner_id), is_transaction=True)
        
        if isinstance(error, pymysql.IntegrityError):
            return None, f"Show with id {show_id} or Partner with id {partner_id} not found, or association already exists."
        if error:
            return None, str(error)
            
        return {"message": "Partner associated successfully", "show_id": show_id, "partner_id": partner_id}, None

    def get_podcasts_for_partner(self, partner_id: str):
        sql = """
            SELECT s.* 
            FROM shows s
            JOIN show_partners sp ON s.id = sp.show_id
            WHERE sp.partner_id = %s
        """
        podcasts, _, error = self._execute_query(sql, (partner_id,), fetch='all')
        if error:
            return [], str(error)
        return podcasts, None

    def create_podcast(self, show_data):
        try:
            print('in create function')
            print(show_data)
            # show_data.pop("annual_usd", None)
            # keys = ["id","title","show_type","subnetwork_name","media_type"]

            # keys = [
            # "id", "title", "minimum_guarantee", "media_type", "tentpole", "relationship_level", "show_type",
            # "evergreen_ownership_pct", "has_sponsorship_revenue", "has_non_evergreen_revenue", "requires_partner_access",
            # "has_branded_revenue", "has_marketing_revenue", "has_web_mgmt_revenue", "genre_id", "is_original",
            # "shows_per_year", "latest_cpm_usd", "ad_slots", "avg_show_length_mins", "start_date", "show_name_in_qbo",
            # "side_bonus_percent", "youtube_ads_percent", "subscriptions_percent", "standard_ads_percent",
            # "sponsorship_ad_fp_lead_percent", "sponsorship_ad_partner_lead_percent", "sponsorship_ad_partner_sold_percent",
            # "programmatic_ads_span_percent", "merchandise_percent", "branded_revenue_percent",
            # "marketing_services_revenue_percent", "direct_customer_hands_off_percent", "youtube_hands_off_percent",
            # "subscription_hands_off_percent", "revenue_2023", "revenue_2024", "revenue_2025",
            # "evergreen_production_staff_name", "show_host_contact", "show_primary_contact", "age_range", "gender",
            # "region", "primary_education", "secondary_education", "genre_name", "subnetwork_name"
            # ]



            # show_dict = {key: None for key in keys}

            # columns = ', '.join([f'`{k}`' for k in show_dict.keys()])
            # print(columns)

            show_id = os.urandom(16).hex()
            show_dict = show_data.dict()
            show_dict['id'] = show_id
            show_dict.pop("annual_usd", None)
            
            show_dict.pop("subnetwork_id", None)

            # Handle JSON serializable fields
            if 'annual_usd' in show_dict and show_dict['annual_usd'] is not None:
                show_dict['annual_usd'] = json.dumps(show_dict['annual_usd'])

            columns = ', '.join([f'`{k}`' for k in show_dict.keys()])
            placeholders = ', '.join(['%s'] * len(show_dict))
            sql = f"INSERT INTO shows ({columns}) VALUES ({placeholders})"
            # sql=f"INSERT INTO shows (id,title) VALUES (1101,'test')"
            values = tuple(show_dict.values())
            print(sql)
            # _, _, error = self._execute_query(sql, is_transaction=True)

            _, _, error = self._execute_query(sql, values, is_transaction=True)
            if error:
                return None, error
            show_id = '1101'
            # Fetch the newly created show to return it
            fetch_sql = "SELECT * FROM shows WHERE id = %s"
            new_show, _, fetch_error = self._execute_query(fetch_sql, (show_id,), fetch='one')
            if fetch_error:
                return None, fetch_error

            return new_show, None
        except Exception as e:
            print(e)
