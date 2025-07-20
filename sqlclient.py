import pymysql
import os
import json
from auth import get_password_hash
from contextlib import contextmanager
from pydantic import BaseModel

# --- Configuration ---
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpassword")
DB_NAME = os.environ.get("DB_NAME", "evergreen")

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
        update_data = show_data.model_dump(exclude_unset=True)
        if not update_data:
            return None, "No update data provided"

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
        show_id = os.urandom(16).hex()
        show_dict = show_data.dict()
        show_dict['id'] = show_id

        # Handle JSON serializable fields
        if 'annual_usd' in show_dict and show_dict['annual_usd'] is not None:
            show_dict['annual_usd'] = json.dumps(show_dict['annual_usd'])

        columns = ', '.join([f'`{k}`' for k in show_dict.keys()])
        placeholders = ', '.join(['%s'] * len(show_dict))
        sql = f"INSERT INTO shows ({columns}) VALUES ({placeholders})"
        values = tuple(show_dict.values())

        _, _, error = self._execute_query(sql, values, is_transaction=True)
        if error:
            return None, error

        # Fetch the newly created show to return it
        fetch_sql = "SELECT * FROM shows WHERE id = %s"
        new_show, _, fetch_error = self._execute_query(fetch_sql, (show_id,), fetch='one')
        if fetch_error:
            return None, fetch_error

        return new_show, None
