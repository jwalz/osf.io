from blinker import ANY
from enum import Enum
from future.moves.urllib.parse import urlparse
from contextlib import contextmanager

from django.utils import timezone

from addons.osfstorage import settings as osfstorage_settings
from api.providers.workflows import Workflows as ModerationWorkflows
from osf.utils.workflows import RegistrationModerationStates as RegStates
from osf_tests import factories

def create_test_file(target, user, filename='test_file', create_guid=True, size=1337, sha256=None):
    osfstorage = target.get_addon('osfstorage')
    root_node = osfstorage.get_root()
    test_file = root_node.append_file(filename)

    if create_guid:
        test_file.get_guid(create=True)

    test_file.create_version(user, {
        'object': '06d80e',
        'service': 'cloud',
        'bucket': 'us-bucket',
        osfstorage_settings.WATERBUTLER_RESOURCE: 'osf',
    }, {
        'size': size,
        'contentType': 'img/png',
        'sha256': sha256,
    }).save()
    return test_file


def create_test_preprint_file(target, user, filename='test_file', create_guid=True, size=1337):
    root_folder = target.root_folder
    test_file = root_folder.append_file(filename)

    if create_guid:
        test_file.get_guid(create=True)

    test_file.create_version(user, {
        'object': '06d80e',
        'service': 'cloud',
        osfstorage_settings.WATERBUTLER_RESOURCE: 'osf',
    }, {
        'size': size,
        'contentType': 'img/png'
    }).save()
    return test_file


def urlparse_drop_netloc(url):
    url = urlparse(url)
    if url[4]:
        return url[2] + '?' + url[4]
    return url[2]


@contextmanager
def disconnected_from_listeners(signal):
    """Temporarily disconnect all listeners for a Blinker signal."""
    listeners = list(signal.receivers_for(ANY))
    for listener in listeners:
        signal.disconnect(listener)
    yield
    for listener in listeners:
        signal.connect(listener)

def only_supports_methods(view, expected_methods):
    if isinstance(view.__class__, type):
        view = view()
    expected_methods.append('OPTIONS')
    return set(expected_methods) == set(view.allowed_methods)


class UserRoles(Enum):
    UNAUTHENTICATED = 0
    NONCONTRIB = 1
    MODERATOR = 2
    READ_USER = 3
    WRITE_USER = 4
    ADMIN_USER = 5

    @classmethod
    def contributor_roles(cls, include_moderator=False):
        base_roles = [cls.READ_USER, cls.WRITE_USER, cls.ADMIN_USER]
        if include_moderator:
            return [cls.MODERATOR, *base_roles]
        return base_roles

    @classmethod
    def noncontributor_roles(cls):
        return [cls.UNAUTHENTICATED, cls.NONCONTRIB, cls.MODERATOR]

    @classmethod
    def write_roles(cls):
        return [cls.WRITE_USER, cls.ADMIN_USER]

    @classmethod
    def excluding(cls, *excluded_roles):
        return [role for role in cls if role not in excluded_roles]

    def get_permissions_string(self):
        if self is UserRoles.READ_USER:
            return 'read'
        if self is UserRoles.WRITE_USER:
            return 'write'
        if self is UserRoles.ADMIN_USER:
            return 'admin'
        return None


def configure_test_registration(registration=None, registration_state=RegStates.ACCEPTED, moderated=True):
    if registration_state is RegStates.PENDING and not moderated:
        raise ValueError('Cannot have Registration pending moderation on a non-moderated provider')

    registration = registration or factories.RegistrationFactory()
    if moderated:
        provider = factories.RegistrationProviderFactory()
        provider.update_group_permissions()
        provider.reviews_workflow = ModerationWorkflows.PRE_MODERATION.value
        provider.save()
        registration.provider = provider

    registration.moderation_state = registration_state.db_name
    if registration_state in RegStates.public_states:
        registration.is_public = True
    else:
        registration.is_public = False

    if registration_state in (RegStates.REJECTED, RegStates.REVERTED):
        registration.deleted = timezone.now()

    registration.save()
    return registration


def configure_test_auth(resource, user_role):
    if user_role is UserRoles.UNAUTHENTICATED:
        return None

    user = factories.AuthUserFactory()
    if user_role is UserRoles.MODERATOR:
        resource.provider.get_group('moderator').user_set.add(user)
    elif user_role in UserRoles.contributor_roles():
        resource.add_contributor(user, user_role.get_permissions_string())

    return user.auth
