-- Make sure FDW exists
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Point the FDW server at the right DB through your tunnel
DROP SERVER IF EXISTS vm_feddata CASCADE;
CREATE SERVER vm_feddata
  FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host '127.0.0.1', port '55432', dbname 'freddata');

-- Map your local role to the remote login (real password here)
CREATE USER MAPPING FOR CURRENT_USER
  SERVER vm_feddata
  OPTIONS (user 'freduser', password 'ChangeMe_Strong1');

-- Schema to hold the foreign tables
CREATE SCHEMA IF NOT EXISTS remote_fdw;

-- Create foreign tables by importing the remote schema
IMPORT FOREIGN SCHEMA public
  FROM SERVER vm_feddata
  INTO remote_fdw;
