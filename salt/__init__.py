# coding: utf-8 -*-
'''
Make me some salt!
'''

# Import python libs
import os
import sys
import warnings

# All salt related deprecation warnings should be shown once each!
warnings.filterwarnings(
    'once',                 # Show once
    '',                     # No deprecation message match
    DeprecationWarning,     # This filter is for DeprecationWarnings
    r'^(salt|salt\.(.*))$'  # Match module(s) 'salt' and 'salt.<whatever>'
)

# While we are supporting Python2.6, hide nested with-statements warnings
warnings.filterwarnings(
    'ignore',
    'With-statements now directly support multiple context managers',
    DeprecationWarning
)

# Import salt libs
# We import log ASAP because we NEED to make sure that any logger instance salt
# instantiates is using salt.log.setup.SaltLoggingClass
import salt.log.setup


# the try block below bypasses an issue at build time so that modules don't
# cause the build to fail
from salt.version import __version__
from salt.utils import migrations

try:
    from salt.utils import parsers, ip_bracket
    from salt.utils.verify import check_user, verify_env, verify_socket
    from salt.utils.verify import verify_files
except ImportError as exc:
    if exc.args[0] != 'No module named _msgpack':
        raise
from salt.exceptions import SaltSystemExit, MasterExit


# Let's instantiate logger using salt.log.setup.logging.getLogger() so pylint
# leaves us alone and stops complaining about an un-used import
logger = salt.log.setup.logging.getLogger(__name__)


class Master(parsers.MasterOptionParser):
    '''
    Creates a master server
    '''
    def prepare(self):
        '''
        Run the preparation sequence required to start a salt master server.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).prepare()
        '''
        self.parse_args()

        try:
            if self.config['verify_env']:
                verify_env(
                    [
                        self.config['pki_dir'],
                        os.path.join(self.config['pki_dir'], 'minions'),
                        os.path.join(self.config['pki_dir'], 'minions_pre'),
                        os.path.join(self.config['pki_dir'],
                                     'minions_rejected'),
                        self.config['cachedir'],
                        os.path.join(self.config['cachedir'], 'jobs'),
                        os.path.join(self.config['cachedir'], 'proc'),
                        self.config['sock_dir'],
                        self.config['token_dir'],
                    ],
                    self.config['user'],
                    permissive=self.config['permissive_pki_access'],
                    pki_dir=self.config['pki_dir'],
                )
                logfile = self.config['log_file']
                if logfile is not None and not logfile.startswith(('tcp://',
                                                                   'udp://',
                                                                   'file://')):
                    # Logfile is not using Syslog, verify
                    verify_files([logfile], self.config['user'])
        except OSError as err:
            sys.exit(err.errno)

        self.setup_logfile_logger()
        logger.info('Setting up the Salt Master')

        if not verify_socket(self.config['interface'],
                             self.config['publish_port'],
                             self.config['ret_port']):
            self.exit(4, 'The ports are not available to bind\n')
        self.config['interface'] = ip_bracket(self.config['interface'])
        migrations.migrate_paths(self.config)

        # Late import so logging works correctly
        import salt.master
        self.master = salt.master.Master(self.config)
        self.daemonize_if_required()
        self.set_pidfile()

    def start(self):
        '''
        Start the actual master.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).start()

        NOTE: Run any required code before calling `super()`.
        '''
        self.prepare()
        if check_user(self.config['user']):
            try:
                self.master.start()
            except MasterExit:
                self.shutdown()
            finally:
                sys.exit()

    def shutdown(self):
        '''
        If sub-classed, run any shutdown operations on this method.
        '''


class Minion(parsers.MinionOptionParser):
    '''
    Create a minion server
    '''
    def prepare(self):
        '''
        Run the preparation sequence required to start a salt minion.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).prepare()
        '''
        self.parse_args()

        try:
            if self.config['verify_env']:
                confd = self.config.get('default_include')
                if confd:
                    # If 'default_include' is specified in config, then use it
                    if '*' in confd:
                        # Value is of the form "minion.d/*.conf"
                        confd = os.path.dirname(confd)
                    if not os.path.isabs(confd):
                        # If configured 'default_include' is not an absolute
                        # path, consider it relative to folder of 'conf_file'
                        # (/etc/salt by default)
                        confd = os.path.join(
                            os.path.dirname(self.config['conf_file']), confd
                        )
                else:
                    confd = os.path.join(
                        os.path.dirname(self.config['conf_file']), 'minion.d'
                    )
                verify_env(
                    [
                        self.config['pki_dir'],
                        self.config['cachedir'],
                        self.config['sock_dir'],
                        self.config['extension_modules'],
                        confd,
                    ],
                    self.config['user'],
                    permissive=self.config['permissive_pki_access'],
                    pki_dir=self.config['pki_dir'],
                )
                logfile = self.config['log_file']
                if logfile is not None and not logfile.startswith(('tcp://',
                                                                   'udp://',
                                                                   'file://')):
                    # Logfile is not using Syslog, verify
                    verify_files([logfile], self.config['user'])
        except OSError as err:
            sys.exit(err.errno)

        self.setup_logfile_logger()
        logger.info(
            'Setting up the Salt Minion "{0}"'.format(
                self.config['id']
            )
        )
        migrations.migrate_paths(self.config)
        # Late import so logging works correctly
        import salt.minion
        # If the minion key has not been accepted, then Salt enters a loop
        # waiting for it, if we daemonize later then the minion could halt
        # the boot process waiting for a key to be accepted on the master.
        # This is the latest safe place to daemonize
        self.daemonize_if_required()
        self.set_pidfile()
        if isinstance(self.config.get('master'), list):
            self.minion = salt.minion.MultiMinion(self.config)
        else:
            self.minion = salt.minion.Minion(self.config)

    def start(self):
        '''
        Start the actual minion.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).start()

        NOTE: Run any required code before calling `super()`.
        '''
        self.prepare()
        try:
            if check_user(self.config['user']):
                self.minion.tune_in()
        except (KeyboardInterrupt, SaltSystemExit) as exc:
            logger.warn('Stopping the Salt Minion')
            if isinstance(exc, KeyboardInterrupt):
                logger.warn('Exiting on Ctrl-c')
            else:
                logger.error(str(exc))
        finally:
            self.shutdown()

    def shutdown(self):
        '''
        If sub-classed, run any shutdown operations on this method.
        '''


class ProxyMinion(parsers.MinionOptionParser):
    '''
    Create a proxy minion server
    '''
    def prepare(self, proxydetails):
        '''
        Run the preparation sequence required to start a salt minion.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).prepare()
        '''
        self.parse_args()

        try:
            if self.config['verify_env']:
                confd = self.config.get('default_include')
                if confd:
                    # If 'default_include' is specified in config, then use it
                    if '*' in confd:
                        # Value is of the form "minion.d/*.conf"
                        confd = os.path.dirname(confd)
                    if not os.path.isabs(confd):
                        # If configured 'default_include' is not an absolute
                        # path, consider it relative to folder of 'conf_file'
                        # (/etc/salt by default)
                        confd = os.path.join(
                            os.path.dirname(self.config['conf_file']), confd
                        )
                else:
                    confd = os.path.join(
                        os.path.dirname(self.config['conf_file']), 'minion.d'
                    )
                verify_env(
                    [
                        self.config['pki_dir'],
                        self.config['cachedir'],
                        self.config['sock_dir'],
                        self.config['extension_modules'],
                        confd,
                    ],
                    self.config['user'],
                    permissive=self.config['permissive_pki_access'],
                    pki_dir=self.config['pki_dir'],
                )
                if 'proxy_log' in proxydetails:
                    logfile = proxydetails['proxy_log']
                else:
                    logfile = None
                if logfile is not None and not logfile.startswith(('tcp://',
                                                                   'udp://',
                                                                   'file://')):
                    # Logfile is not using Syslog, verify
                    verify_files([logfile], self.config['user'])
        except OSError as err:
            sys.exit(err.errno)

        self.config['proxy'] = proxydetails
        self.setup_logfile_logger()
        logger.info(
            'Setting up a Salt Proxy Minion "{0}"'.format(
                self.config['id']
            )
        )
        migrations.migrate_paths(self.config)
        # Late import so logging works correctly
        import salt.minion
        # If the minion key has not been accepted, then Salt enters a loop
        # waiting for it, if we daemonize later then the minion could halt
        # the boot process waiting for a key to be accepted on the master.
        # This is the latest safe place to daemonize
        self.daemonize_if_required()
        self.set_pidfile()
        if isinstance(self.config.get('master'), list):
            self.minion = salt.minion.MultiMinion(self.config)
        else:
            self.minion = salt.minion.ProxyMinion(self.config)

    def start(self, proxydetails):
        '''
        Start the actual minion.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).start()

        NOTE: Run any required code before calling `super()`.
        '''
        self.prepare(proxydetails)
        try:
            self.minion.tune_in()
        except (KeyboardInterrupt, SaltSystemExit) as exc:
            logger.warn('Stopping the Salt Proxy Minion')
            if isinstance(exc, KeyboardInterrupt):
                logger.warn('Exiting on Ctrl-c')
            else:
                logger.error(str(exc))
        finally:
            self.shutdown()

    def shutdown(self):
        '''
        If sub-classed, run any shutdown operations on this method.
        '''
        if 'proxy' in self.minion.opts:
            self.minion.opts['proxyobject'].shutdown(self.minion.opts)


class Syndic(parsers.SyndicOptionParser):
    '''
    Create a syndic server
    '''

    def prepare(self):
        '''
        Run the preparation sequence required to start a salt syndic minion.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).prepare()
        '''
        self.parse_args()
        try:
            if self.config['verify_env']:
                verify_env(
                    [
                        self.config['pki_dir'],
                        self.config['cachedir'],
                        self.config['sock_dir'],
                        self.config['extension_modules'],
                    ],
                    self.config['user'],
                    permissive=self.config['permissive_pki_access'],
                    pki_dir=self.config['pki_dir'],
                )
                logfile = self.config['log_file']
                if logfile is not None and not logfile.startswith(('tcp://',
                                                                   'udp://',
                                                                   'file://')):
                    # Logfile is not using Syslog, verify
                    verify_files([logfile], self.config['user'])
        except OSError as err:
            sys.exit(err.errno)

        self.setup_logfile_logger()
        logger.info(
            'Setting up the Salt Syndic Minion "{0}"'.format(
                self.config['id']
            )
        )

        # Late import so logging works correctly
        import salt.minion
        self.daemonize_if_required()
        self.syndic = salt.minion.Syndic(self.config)
        self.set_pidfile()

    def start(self):
        '''
        Start the actual syndic.

        If sub-classed, don't **ever** forget to run:

            super(YourSubClass, self).start()

        NOTE: Run any required code before calling `super()`.
        '''
        self.prepare()
        if check_user(self.config['user']):
            try:
                self.syndic.tune_in()
            except KeyboardInterrupt:
                logger.warn('Stopping the Salt Syndic Minion')
                self.shutdown()

    def shutdown(self):
        '''
        If sub-classed, run any shutdown operations on this method.
        '''
