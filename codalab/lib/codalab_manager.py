'''
A CodaLabManager instance stores all the information needed for the CLI, which
is synchronized with a set of JSON files in the CodaLab directory.  It contains
two types of information:

- Configuration (permanent):
  * Aliases: name (e.g., "main") -> address (e.g., http://codalab.org:2800)
- State (transient):
  * address -> username, auth_info
  * session_name -> address, worksheet_uuid

This class provides helper methods that initialize each of the main CodaLab
classes based on the configuration in this file:

  codalab_home: returns the CodaLab home directory
  bundle_store: returns a BundleStore
  cli: returns a BundleCLI
  client: returns a BundleClient
  model: returns a BundleModel
  rpc_server: returns a BundleRPCServer

Imports in this file are deferred to as late as possible because some of these
modules (ex: the model) depend on heavy-weight library imports (ex: sqlalchemy).

As an added benefit of the lazy importing and initialization, note that a config
file that specifies enough information to construct some of these classes is
still valid. For example, the config file for a remote client will not need to
include any server configuration.
'''
import getpass
import json
import os
import sys
import time
import psutil
import tempfile

from codalab.client import is_local_address
from codalab.common import UsageError, PermissionError
from codalab.objects.worksheet import Worksheet
from codalab.server.auth import User
from codalab.lib.bundle_store import BundleStore

def cached(fn):
    def inner(self):
        if fn.__name__ not in self.cache:
            self.cache[fn.__name__] = fn(self)
        return self.cache[fn.__name__]
    return inner

def write_pretty_json(data, path):
    out = open(path, 'w')
    print >>out, json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))
    out.close()

def read_json_or_die(path):
    try:
        with open(path, 'rb') as f:
            string = f.read()
        return json.loads(string)
    except ValueError as e:
        print "Invalid JSON in %s:\n%s" % (path, string)
        print e
        sys.exit(1)

class CodaLabManager(object):
    '''
    temporary: don't use config files
    '''
    def __init__(self, temporary=False, clients=None):
        self.cache = {}
        self.temporary = temporary

        if self.temporary:
            self.config = {}
            self.state = {'auth': {}, 'sessions': {}}
            self.clients = clients
            return

        # Read config file, creating if it doesn't exist.
        config_path = self.config_path()
        if not os.path.exists(config_path):
            write_pretty_json({
                'cli': {'verbose': 1},
                'server': {'class': 'SQLiteModel', 'host': 'localhost', 'port': 2800,
                    'auth': {'class': 'MockAuthHandler'}, 'verbose': 1},
                'aliases': {
                    'localhost': 'http://localhost:2800',
                    'main': 'https://codalab.org/bundleservice',
                },
                'workers': {
                    'q': {
                        'verbose': 1,
                        #'docker_image': 'codalab/ubuntu:1.7',
                        'dispatch_command': "python $CODALAB_CLI/scripts/dispatch-q.py",
                    }
                }
            }, config_path)
        self.config = read_json_or_die(config_path)

        # Substitute environment variables
        codalab_cli = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        def replace(x):
            if isinstance(x, basestring):
                return x.replace('$CODALAB_CLI', codalab_cli)
            if isinstance(x, dict):
                return dict((k, replace(v)) for k, v in x.items())
            return x
        self.config = replace(self.config)

        # Read state file, creating if it doesn't exist.
        state_path = self.state_path()
        if not os.path.exists(state_path):
            write_pretty_json({
                'auth': {},      # address -> {username, auth_token}
                'sessions': {},  # session_name -> {address, worksheet_uuid, last_modified}
            }, state_path)
        self.state = read_json_or_die(state_path)

        self.clients = {}  # map from address => client

    @cached
    def config_path(self): return os.path.join(self.codalab_home(), 'config.json')

    @cached
    def state_path(self): return os.path.join(self.codalab_home(), 'state.json')

    @cached
    def codalab_home(self):
        from codalab.lib import path_util
        # Default to this directory in the user's home directory.
        # In the future, allow customization based on.
        home = os.getenv('CODALAB_HOME', '~/.codalab')
        home = path_util.normalize(home)
        path_util.make_directory(home)
        # Global setting!  Make temp directory the same as the bundle store
        # temporary directory.  The default /tmp generally doesn't have enough
        # space.
        tempfile.tempdir = os.path.join(home, BundleStore.TEMP_SUBDIRECTORY)
        return home

    @cached
    def bundle_store(self):
        codalab_home = self.codalab_home()
        direct_upload_paths = self.config['server'].get('direct_upload_paths', [])
        return BundleStore(codalab_home, direct_upload_paths)

    def apply_alias(self, key):
        return self.config['aliases'].get(key, key)

    @cached
    def session_name(self):
        '''
        Return the current session name.
        '''
        if self.temporary:
            return 'temporary'

        # If specified in the environment, then return that.
        session = os.getenv('CODALAB_SESSION')
        if session:
            return session

        # Otherwise, go up process hierarchy to the *highest up shell*.  This
        # way, it's easy to write scripts that have embedded 'cl' commands
        # which modify the current session.
        process = psutil.Process(os.getppid())
        session = 'top'
        max_depth = 10
        while process and max_depth:
            # TODO: test this on Windows
            if process.name() in ('bash', 'csh', 'zsh'):
                session = str(process.pid)
            process = process.parent()
            max_depth = max_depth - 1

        return session

    @cached
    def session(self):
        '''
        Return the current session.
        '''
        sessions = self.state['sessions']
        name = self.session_name()
        if name not in sessions:
            # New session: set the address and worksheet uuid to the default (local if not specified)
            cli_config = self.config.get('cli', {})
            address = cli_config.get('default_address', 'local')
            worksheet_uuid = cli_config.get('default_worksheet_uuid', '')
            sessions[name] = {'address': address, 'worksheet_uuid': worksheet_uuid}
        return sessions[name]

    @cached
    def model(self):
        '''
        Return a model.  Called by the server.
        '''
        model_class = self.config['server']['class']
        model = None
        if model_class == 'MySQLModel':
            from codalab.model.mysql_model import MySQLModel
            model = MySQLModel(engine_url=self.config['server']['engine_url'])
        elif model_class == 'SQLiteModel':
            codalab_home = self.codalab_home()
            from codalab.model.sqlite_model import SQLiteModel
            model = SQLiteModel(codalab_home)
        else:
            raise UsageError('Unexpected model class: %s, expected MySQLModel or SQLiteModel' % (model_class,))
        model.root_user_id = self.root_user_id()
        return model

    def auth_handler(self, mock=False):
        '''
        Returns a class to authenticate users on the server-side.  Called by the server.
        '''
        auth_config = self.config['server']['auth']
        handler_class = auth_config['class']

        if mock or handler_class == 'MockAuthHandler':
            return self.mock_auth_handler()
        if handler_class == 'OAuthHandler':
            return self.oauth_handler()
        raise UsageError('Unexpected auth handler class: %s, expected OAuthHandler or MockAuthHandler' % (handler_class,))

    @cached
    def mock_auth_handler(self):
        from codalab.server.auth import MockAuthHandler
        # Just create one user corresponding to the root
        users = [User(self.root_user_name(), self.root_user_id())]
        return MockAuthHandler(users)

    @cached
    def oauth_handler(self):
        arguments = ('address', 'app_id', 'app_key')
        auth_config = self.config['server']['auth']
        kwargs = {arg: auth_config[arg] for arg in arguments}
        from codalab.server.auth import OAuthHandler
        return OAuthHandler(**kwargs)

    def root_user_name(self):
        return self.config['server'].get('root_user_name', 'codalab')
    def root_user_id(self):
        return self.config['server'].get('root_user_id', '0')

    def local_client(self):
        return self.client('local')

    def current_client(self):
        return self.client(self.session()['address'])

    def client(self, address, is_cli=True):
        '''
        Return a client given the address.  Note that this can either be called
        by the CLI (is_cli=True) or the server (is_cli=False).
        If called by the CLI, we don't need to authenticate.
        Cache the Client if necessary.
        '''
        if address in self.clients:
            return self.clients[address]
        # if local force mockauth or if locl server use correct auth
        if is_local_address(address):
            bundle_store = self.bundle_store()
            model = self.model()
            auth_handler = self.auth_handler(mock=is_cli)

            from codalab.client.local_bundle_client import LocalBundleClient
            client = LocalBundleClient(address, bundle_store, model, auth_handler, self.cli_verbose)
            self.clients[address] = client
            if is_cli:
                # Set current user
                access_token = self._authenticate(client)
                auth_handler.validate_token(access_token)
        else:
            from codalab.client.remote_bundle_client import RemoteBundleClient
            client = RemoteBundleClient(address, lambda a_client: self._authenticate(a_client), self.cli_verbose())
            self.clients[address] = client
            self._authenticate(client)
        return client

    def cli_verbose(self): return self.config.get('cli', {}).get('verbose')

    def _authenticate(self, client):
        '''
        Authenticate with the given client. This will prompt user for password
        unless valid credentials are already available. Client state will be
        updated if new tokens are generated.

        client: The client pointing to the bundle service to authenticate with.

        Returns an access token.
        '''
        address = client.address
        auth = self.state['auth'].get(address, {})
        def _cache_token(token_info, username=None):
            '''
            Helper to update state with new token info and optional username.
            Returns the latest access token.
            '''
            # Make sure this is in sync with auth.py.
            token_info['expires_at'] = time.time() + float(token_info['expires_in'])
            del token_info['expires_in']
            auth['token_info'] = token_info
            if username is not None:
                auth['username'] = username
            self.save_state()
            return token_info['access_token']

        # Check the cache for a valid token
        if 'token_info' in auth:
            token_info = auth['token_info']
            expires_at = token_info.get('expires_at', 0.0)
            if expires_at > time.time():
                # Token is usable but check if it's nearing expiration (10 minutes)
                # If not nearing, then just return it.
                if expires_at >= (time.time() + 10 * 60):
                    return token_info['access_token']
                # Otherwise, let's refresh the token.
                token_info = client.login('refresh_token',
                                          auth['username'],
                                          token_info['refresh_token'])
                if token_info is not None:
                    return _cache_token(token_info)

        # If we get here, a valid token is not already available.
        auth = self.state['auth'][address] = {}

        username = None
        # For a local client with mock credentials, use the default username.
        if is_local_address(client.address):
            username = self.root_user_name()
            password = ''
        if not username:
            print 'Requesting access at %s' % address
            sys.stdout.write('Username: ')  # Use write to avoid extra space
            username = sys.stdin.readline().rstrip()
            password = getpass.getpass()

        token_info = client.login('credentials', username, password)
        if token_info is None:
            raise PermissionError("Invalid username or password.")
        return _cache_token(token_info, username)

    def get_current_worksheet_uuid(self):
        '''
        Return a worksheet_uuid for the current worksheet, or None if there is none.

        This method uses the current parent-process id to return the same result
        across multiple invocations in the same shell.
        '''
        session = self.session()
        client = self.client(session['address'])
        worksheet_uuid = session.get('worksheet_uuid', None)
        if not worksheet_uuid:
            worksheet_uuid = client.get_worksheet_uuid(None, '')
        return (client, worksheet_uuid)

    def set_current_worksheet_uuid(self, client, worksheet_uuid):
        '''
        Set the current worksheet to the given worksheet_uuid.
        '''
        session = self.session()
        session['address'] = client.address
        if worksheet_uuid:
            session['worksheet_uuid'] = worksheet_uuid
        else:
            if 'worksheet_uuid' in session: del session['worksheet_uuid']
        self.save_state()

    def logout(self, client):
        del self.state['auth'][client.address]  # Clear credentials
        self.save_state()

    def save_config(self):
        if self.temporary: return
        write_pretty_json(self.config, self.config_path())

    def save_state(self):
        if self.temporary: return
        write_pretty_json(self.state, self.state_path())
