#!/usr/bin/python3
#activate_this = '/var/www/catalog/venv/Scripts/activate_this.py'
#exec(open(activate_this).read(), dict(__file__=activate_this))

import sys
import logging
logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/var/www/catalog/")

from main import app as application
application.secret_key = 'catalogapplication'
