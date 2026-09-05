-- @file create_users.sql
-- creates a user table with columns id, email, password, created_at
-- password is hashed when stored.
-- @author Tony Shin <tonyshin4065@gmail.com>


CREATE TABLE IF NOT EXISTS users(
	id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
	email TEXT NOT NULL UNIQUE,
	password TEXT NOT NULL,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
