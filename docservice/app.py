from functools import wraps
import os
import requests
import secrets
import importlib.metadata
from flask import Flask, request, session, make_response, redirect, Response
from flask_cors import CORS

import logging

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration


class CertificateError(Exception):
    def __init__(self, message="invalid certificate"):
        self.message = message
        super().__init__(self.message)


sentry_sdk.init(
    dsn='https://452458c2a6630292629364221bff0dee@o4505709665976320' +
        '.ingest.sentry.io/4505709666762752',
    integrations=[
        FlaskIntegration(),
    ],

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=1.0,

    release='docservice:' + importlib.metadata.version("docservice"),
    environment=os.environ.get('SENTRY_ENVIRONMENT', 'dev'),
)

# from flask_oidc import OpenIDConnect
logger = logging.getLogger(__name__)


def urljoin_multipart(*args):
    """Join multiple parts of a URL together, ignoring empty parts."""
    logger.info('urljoin_multipart: %s', args)
    return '/'.join(
        [arg.strip('/')
         for arg in args if arg is not None and arg.strip('/') != '']
    )


try:
    from jupyterhub.services.auth import HubOAuth
    auth = HubOAuth(
        api_token=os.environ['JUPYTERHUB_API_TOKEN'], cache_max_age=60)
except Exception:
    logger.warning('Auth system not configured')
    auth = None


url_prefix = os.getenv('JUPYTERHUB_SERVICE_PREFIX', '').rstrip('/')


def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SECRET_KEY'] = os.environ.get(
        'FLASK_SECRET', secrets.token_bytes(32))
    app.secret_key = app.config['SECRET_KEY']

    app.config['DOC_URL'] = \
        os.getenv('DOC_URL', 'http://lst-doc:80').strip('/')
    app.config['CTADS_DISABLE_ALL_AUTH'] = \
        os.getenv('CTADS_DISABLE_ALL_AUTH', 'False') == 'True'

    return app


app = create_app()


def authenticated(f):
    # TODO: here do a permission check;
    # in the future, the check will be done with rucio maybe
    """Decorator for authenticating with the Hub via OAuth"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if app.config['CTADS_DISABLE_ALL_AUTH']:
            return f({'name': 'anonymous', 'admin': True}, *args, **kwargs)
        else:
            if auth is None:
                return 'Unable to use jupyterhub to verify access to this\
                    service. At this time, the docservice uses jupyterhub\
                    to control access to protected resources', 500

            header = request.headers.get('Authorization')
            if header and header.startswith('Bearer '):
                header_token = header.removeprefix('Bearer ')
            else:
                header_token = None

            token = session.get('token') \
                or request.args.get('token') \
                or header_token

            if token:
                user = auth.user_for_token(token)
                if user is not None and not auth.check_scopes(
                        'access:services!service=docservice', user):
                    return 'Access denied, token scopes are insufficient. ' + \
                        'If you need access to this service, please ' + \
                        'contact CTA-CH DC team at EPFL.', 403
            else:
                user = None

            if user:
                return f(user, *args, **kwargs)
            else:
                # redirect to login url on failed auth
                state = auth.generate_state(next_url=request.path)
                response = make_response(
                    redirect(auth.login_url + '&state=%s' % state)
                )
                response.set_cookie(auth.state_cookie_name, state)
                return response

    return decorated


@app.route(url_prefix + '/oauth_callback')
def oauth_callback():
    code = request.args.get('code', None)
    if code is None:
        return 'Error: oauth callback code', 403

    # validate state field
    arg_state = request.args.get('state', None)
    cookie_state = request.cookies.get(auth.state_cookie_name)
    if arg_state is None or arg_state != cookie_state:
        # state doesn't match
        return 'Error: oauth callback invalid state', 403

    token = auth.token_for_code(code)
    # store token in session cookie
    session['token'] = token
    next_url = auth.get_next_url(cookie_state) or url_prefix
    return make_response(redirect(next_url))


@app.route(url_prefix + '/', defaults={'path': ''})
@app.route(url_prefix + '/<path:path>')
@authenticated
def default(user, path):
    default_chunk_size = 10 * 1024 * 1024

    def request_datastream():
        while (buf := request.stream.read(default_chunk_size)) != b'':
            yield buf

    # Exclude all "hop-by-hop headers" defined by RFC 2616
    # section 13.5.1 ref. https://www.rfc-editor.org/rfc/rfc2616#section-13.5.1
    excluded_headers = ['content-encoding', 'content-length',
                        'transfer-encoding', 'connection', 'keep-alive',
                        'proxy-authenticate', 'proxy-authorization', 'te',
                        'trailers', 'upgrade']

    res = requests.request(
        method=request.method,
        url=app.config['DOC_URL']+'/'+path,
        headers={k: v for k, v in request.headers
                 if k.lower() not in ['host', 'authorization'] and
                 k.lower() not in excluded_headers},
        data=request_datastream(),
        cookies=request.cookies,
        allow_redirects=False,
    )

    headers = [
        (k, v) for k, v in res.raw.headers.items()
        if k.lower() not in excluded_headers
    ]

    return Response(res.content, res.status_code, headers)
