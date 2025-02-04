# Copyright 2014-2015 Canonical Limited.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import hashlib
import re

from charmhelpers.fetch import (
    BaseFetchHandler,
    UnhandledSource
)
from charmhelpers.payload.archive import (
    get_archive_handler,
    extract,
)
from charmhelpers.core.host import mkdir, check_hash

from urllib.request import (
    build_opener, install_opener, urlopen, urlretrieve,
    HTTPPasswordMgrWithDefaultRealm, HTTPBasicAuthHandler,
)
from urllib.parse import urlparse, urlunparse, parse_qs
from urllib.error import URLError


def splituser(host):
    _userprog = re.compile('^(.*)@(.*)$')
    match = _userprog.match(host)
    if match:
        return match.group(1, 2)
    return None, host


def splitpasswd(user):
    _passwdprog = re.compile('^([^:]*):(.*)$', re.S)
    match = _passwdprog.match(user)
    if match:
        return match.group(1, 2)
    return user, None


class ArchiveUrlFetchHandler(BaseFetchHandler):
    """
    Handler to download archive files from arbitrary URLs.

    Can fetch from http, https, ftp, and file URLs.

    Can install either tarballs (.tar, .tgz, .tbz2, etc) or zip files.

    Installs the contents of the archive in $CHARM_DIR/fetched/.
    """
    def can_handle(self, source):
        url_parts = self.parse_url(source)
        if url_parts.scheme not in ('http', 'https', 'ftp', 'file'):
            # XXX: Why is this returning a boolean and a string? It's
            # doomed to fail since "bool(can_handle('foo://'))"  will be True.
            return "Wrong source type"
        if get_archive_handler(self.base_url(source)):
            return True
        return False

    def download(self, source, dest):
        """
        Download an archive file.

        :param str source: URL pointing to an archive file.
        :param str dest: Local path location to download archive file to.
        """
        # propagate all exceptions
        # URLError, OSError, etc
        proto, netloc, path, params, query, fragment = urlparse(source)
        if proto in ('http', 'https'):
            auth, barehost = splituser(netloc)
            if auth is not None:
                source = urlunparse((proto, barehost, path, params, query, fragment))
                username, password = splitpasswd(auth)
                passman = HTTPPasswordMgrWithDefaultRealm()
                # Realm is set to None in add_password to force the username and password
                # to be used whatever the realm
                passman.add_password(None, source, username, password)
                authhandler = HTTPBasicAuthHandler(passman)
                opener = build_opener(authhandler)
                install_opener(opener)
        response = urlopen(source)
        try:
            with open(dest, 'wb') as dest_file:
                dest_file.write(response.read())
        except Exception as e:
            if os.path.isfile(dest):
                os.unlink(dest)
            raise e

    # Mandatory file validation via Sha1 or MD5 hashing.
    def download_and_validate(self, url, hashsum, validate="sha1"):
        tempfile, headers = urlretrieve(url)
        check_hash(tempfile, hashsum, validate)
        return tempfile

    def install(self, source, dest=None, checksum=None, hash_type='sha1'):
        """
        Download and install an archive file, with optional checksum validation.

        The checksum can also be given on the `source` URL's fragment.
        For example::

            handler.install('http://example.com/file.tgz#sha1=deadbeef')

        :param str source: URL pointing to an archive file.
        :param str dest: Local destination path to install to. If not given,
            installs to `$CHARM_DIR/archives/archive_file_name`.
        :param str checksum: If given, validate the archive file after download.
        :param str hash_type: Algorithm used to generate `checksum`.
            Can be any hash alrgorithm supported by :mod:`hashlib`,
            such as md5, sha1, sha256, sha512, etc.

        """
        url_parts = self.parse_url(source)
        dest_dir = os.path.join(os.environ.get('CHARM_DIR'), 'fetched')
        if not os.path.exists(dest_dir):
            mkdir(dest_dir, perms=0o755)
        dld_file = os.path.join(dest_dir, os.path.basename(url_parts.path))
        try:
            self.download(source, dld_file)
        except URLError as e:
            raise UnhandledSource(e.reason)
        except OSError as e:
            raise UnhandledSource(e.strerror)
        options = parse_qs(url_parts.fragment)
        for key, value in options.items():
            algorithms = hashlib.algorithms_available
            if key in algorithms:
                if len(value) != 1:
                    raise TypeError(
                        "Expected 1 hash value, not %d" % len(value))
                expected = value[0]
                check_hash(dld_file, expected, key)
        if checksum:
            check_hash(dld_file, checksum, hash_type)
        return extract(dld_file, dest)
