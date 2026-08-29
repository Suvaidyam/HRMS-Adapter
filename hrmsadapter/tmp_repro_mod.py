import frappe
from frappe.app import init_request
from frappe.auth import validate_auth
from werkzeug.wrappers import Request
from werkzeug.test import EnvironBuilder
import traceback

def run():
    builder = EnvironBuilder(path='/', method='GET', headers={'Host':'hrm.localhost'})
    env = builder.get_environ()
    request = Request(env)
    try:
        init_request(request)
        validate_auth()
        from frappe.website.serve import get_response
        resp = get_response()
        print('OK RESPONSE', resp)
    except Exception as e:
        print('CAUGHT EXCEPTION:')
        traceback.print_exc()
