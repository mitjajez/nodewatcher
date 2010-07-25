#!/usr/bin/env python

# This script prepares the database for nodewatcher and optionally injects existing data from dump file (passed as argument)

# Setup import paths, since we are using Django models
import sys, os
sys.path.append('..')
os.environ['DJANGO_SETTINGS_MODULE'] = 'web.settings'

# Imports
from django.db import connection, transaction
from django.conf import settings
from django.core import serializers
from django.core.management.color import no_style
import time
from traceback import print_exc
import subprocess

if len(sys.argv) > 2:
  print "Usage: %s [<dump file>]" % sys.argv[0]
  exit(1)

def ensure_success(errcode):
  if errcode != 0:
    print "ERROR: Command failed to execute, aborting!"
    exit(1)

db_backend = settings.DATABASES['default']['ENGINE']
if db_backend.startswith('postgresql'):
  db_backend = 'postgresql'
elif db_backend.startswith('sqlite'):
  db_backend = 'sqlite'
elif db_backend.startswith('mysql'):
  db_backend = 'mysql'

if os.path.isfile('scripts/%s_init.sh' % db_backend):
  print "!!! NOTE: A setup script exists for your database. Be sure that it"
  print "!!! does what you want before continuing! You may have to edit the"
  print "!!! script and YOU MUST REVIEW IT! Otherwise the script may bork"
  print "!!! your installation. Press CTRL + C to abort now."

  try:
    time.sleep(5)
  except KeyboardInterrupt:
    exit(1)

  print ">>> Executing database setup script 'scripts/%s_init.sh'..." % db_backend
  ensure_success(subprocess.call(["scripts/%s_init.sh" % db_backend, settings.DATABASES['default']['NAME']]))
else:
  print "!!! NOTE: This script assumes that you have created and configured"
  print "!!! a proper database via settings.py! The database MUST be completely"
  print "!!! empty (no tables or sequences should be present). If this is not"
  print "!!! the case, this operation WILL FAIL! Press CTRL+C to abort now."
  
  if db_backend == 'postgresql':
    print "!!!"
    print "!!! You are using a PostgreSQL database. Be sure that you have"
    print "!!! installed the IP4R extension or schema sync WILL FAIL!"
    print "!!! "
    print "!!! More information: http://ip4r.projects.postgresql.org"
    print "!!!"
  
  try:
    time.sleep(5)
  except KeyboardInterrupt:
    exit(1)

print ">>> Performing initial database sync..."
if len(sys.argv) < 2:
  ensure_success(subprocess.call([sys.executable, "-u", "manage.py", "syncdb"]))
else:
  ensure_success(subprocess.call([sys.executable, "-u", "manage.py", "syncdb", "--noinput"]))

if len(sys.argv) < 2:
  print ">>> Initialization completed."
else:
  print ">>> Performing data cleanup..."
  try:
    cursor = connection.cursor()
    cursor.execute("DELETE FROM auth_group_permissions")
    cursor.execute("DELETE FROM auth_group")
    cursor.execute("DELETE FROM auth_permission")
    cursor.execute("DELETE FROM auth_user")
    cursor.execute("DELETE FROM django_content_type")
    cursor.execute("DELETE FROM django_site")
    cursor.execute("DELETE FROM policy_trafficcontrolclass")
    transaction.commit_unless_managed()
  except:
    print "ERROR: Data cleanup operation failed, aborting!"
    exit(1)
  
  print ">>> Importing data from '%s'..." % sys.argv[1]
  
  if db_backend == 'mysql':
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
  elif db_backend == 'sqlite':
    cursor.execute("PRAGMA foreign_keys = 0")
  
  transaction.commit_unless_managed()
  transaction.enter_transaction_management()
  transaction.managed(True)
  
  models = set()
  
  try:
    count = 0
    for holder in serializers.deserialize('json', open(sys.argv[1], 'r')):
      models.add(holder.object.__class__)
      holder.save()
      count += 1
    print "Installed %d object(s)" % count
  except:
    transaction.rollback()
    transaction.leave_transaction_management()
  
    print_exc()
    print "ERROR: Data import operation failed, aborting!"
    exit(1)
  
  # Reset sequences
  for line in connection.ops.sequence_reset_sql(no_style(), models):
    cursor.execute(line)
  
  transaction.commit()
  transaction.leave_transaction_management()
  connection.close()
  
  print ">>> Import completed."
