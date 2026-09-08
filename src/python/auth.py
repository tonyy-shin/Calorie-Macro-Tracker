"""
@file auth.py
This file does the following things:
        1. registers new users
        2. verifies the users by fetching the hash by email.
@author Tony Shin <tonyshin4065@gmail.com>
"""

import psycopg
import bcrypt


def register_user(conn, email, password):
        """
        Registers new users to the users table.
        @param conn - connection with database
        @param email - user's email
        @param password - user's actual password (not hashed yet)
        @return user_id or None
        """
        hashed_pwd = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
                with conn.cursor() as cur:
                        cur.execute("INSERT INTO users (email, password) VALUES (%s, %s) RETURNING id",
                                (email, hashed_pwd))
                        user_id = cur.fetchone()[0]
                conn.commit()
                return user_id
        except psycopg.errors.UniqueViolation:
                conn.rollback()
                return None


def verify_user(conn, email, password):
        """
        Verifies if user is in database.
        @param conn - connection with database
        @param email - user's email
        @param password - user's actual password (not hashed)
        @return user_id or None
        """
        cur = conn.cursor()
        cur.execute("SELECT id,password FROM users WHERE email = %s", (email,))
        row = cur.fetchone()

        if row is None:
                return None

        id, stored_hash = row

        if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                return id
        return None
