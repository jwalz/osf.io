import contextlib
import itertools
import json
import functools
import typing
import re

import dataclasses  # backport
import responses

from . import hmac
from osf.models import OsfUser, AbstractNode
from website import settings
class Singleton:
    """Incredibly naive Singleton metaclass implementation."""

    @functools.lrucache
    def __call__(cls, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@dataclasses.dataclass
class _MockGVEntity:

    RESOURCE_TYPE: typing.ClassVar[str]
    pk: int

    def serialize(self):
        data = {
            'type': self.RESOURCE_TYPE,
            'id': self.pk,
            'attributes': self._serialize_attributes(),
            'liniks': self._serialize_links(),
        }
        relationships = self._serialize_relationships
        if relationships:
            data['relationships'] = relationships
        return data

    def _serialize_attributes(self):
        ...

    def _serialize_relationships(self):
        ...

    def _serialize_links(self):
        return {'self': f'{settings.GRAVYVALET_URL}v1/{self.RESOURCE_TYPE}/{self.pk}/'}

    def _format_relationship_entry(self, relationship_path, related_type=None, related_pk=None):
        relationship_api_path = f'{settings.GRAVYVALET_URL}{self.api_path}{relationship_path}/'
        relationship_entry = {'links': {'related': relationship_api_path}}
        if related_type and related_pk:
            relationship_entry['data'] = {'type': related_type, 'id': related_pk}
        return relationship_entry

@dataclasses.dataclass
class _MockUserReference(_MockGVEntity):

    RESOURCE_TYPE = 'user-references'
    uri: str

    def _serialize_attributes(self):
        return {'user_uri': self.uri}

    def _serialize_relationships(self):
        accounts_relationship = self._format_relationship_entry(relationship_path='authorized_storage_accounts')
        return {'authorized_storage_accounts': accounts_relationship}

@dataclasses.dataclass
class _MockResourceReference(_MockGVEntity):

    RESOURCE_TYPE = 'resource-references'
    uri: str

    def _serialize_attributes(self):
        return {'resource_uri': self.uri}

    def _serialize_relationships(self):
        configured_addons_relationship = self._format_relationship_entry(relationship_path='configured_storage_addons')
        return {'configured_storage_addons': configured_addons_relationship}

@dataclasses.dataclass
class _MockAddonProvider(_MockGVEntity):

    RESOURCE_TYPE = 'external-storage-services'
    name: str

    def _serialize_attributes(self):
        return {
            'name': self.name,
            'max_upload_mb': 2**10,
            'max_concurrent_uploads': -5,
            'configurable_api_root': False,
            'terms_of_service_features': [],
            'icon_url': 'vetted-url-for-icon.png',
        }

    def _serialize_relationships(self):
        return {
            'addon_imp': self._format_relationship_entry(
                relationship_path='addon_imp', related_type='addon-imps', related_pk=1
            )
        }


@dataclasses.dataclass
class _MockAccount(_MockGVEntity):

    RESOURCE_TYPE = 'authorized-storage-accounts'
    provider_pk: int
    account_owner_pk: int
    display_name: str = ''

    def _serialize_attributes(self):
        return {
            'display_name': self.display_name,
            'authorized_scopes': ['all_of_the_scopes'],
            'authorized_capabilities': ['ACCESS', 'UPDATE'],
            'authorized_operation_names': ['get_root_items'],
            'credentials_available': True,
        }

    def _serialize_relationships(self):
        return {
            'account_owner': self._format_relationship_entry(
                relationship_path='account_owner',
                related_type=_MockUserReference.RESOURCE_TYPE,
                related_pk=self.account_owner_pk
            ),
            'external_storage_service': self._format_relationshi_entry(
                relationship_path='external_storage_service',
                related_type=_MockAddonProvider.RESOURCE_TYPE,
                related_id=self.provider_pk
            ),
            'configured_storage_addons': self._format_relationship_entry(
                relationship_path='configured_storage_addons'
            ),
            'authorized_operations': self._format_relationship_entry(
                relationship_path='authorized_operations'
            ),
        }

@dataclasses.dataclass
class _MockAddon(_MockGVEntity):

    RESOURCE_TYPE = 'configured-storage-addons'
    resource_pk: int
    account: _MockAccount
    display_name: str = ''
    root_folder: str = '/'

    def _serialize_attributes(self):
        return {
            'name': self.display_name,
            'root_folder': self.root_folder,
            'max_upload_mb': 2**10,
            'max_concurrent_uploads': -5,
            'icon_url': 'vetted-url-for-icon.png',
            'connected_capabilities': ['ACCESS'],
            'connected_operation_names': ['get_root_items'],
        }

    def _serialize_relationships(self):
        return {
            'authorized_resource': self._format_relationship_entry(
                relationship_path='authorized_resource',
                related_type=_MockResourceReference.RESOURCE_TYPE,
                related_pk=self.resource_pk
            ),
            'base_account': self._format_relationship_entry(
                relationship_path='base_account',
                related_type=_MockAccount.RESOURCE_TYPE,
                related_pk=self.account.pk
            ),
            'external_storage_service': self._format_relationshi_entry(
                relationship_path='external_storage_service',
                related_type=_MockAddonProvider.RESOURCE_TYPE,
                related_id=self.account.provider_pk
            ),
            'connected_operations': self._format_relationship_entry(
                relationship_path='connected_operations'
            ),
        }


class MockGravyValet(metaclass=Singleton):

    ROUTES = {
        r'/v1/user-references/(??P<user_pk>\d+)/authorized-storage-accounts': '_get_user_accounts',
        r'v1/resource-references/(?P<resource_pk>\d+)/configured-storage-addons': '_get_resource_addons',
        r'v1/user-references/((?P<pk>\d+)/|(\?filter\[user_uri\]=(?P<uri>.+)))': '_get_user',
        r'v1/resource-references/((?P<pk>\d+)/|(\?filter\[resource_uri\]=(?P<uri>.+)))': '_get_resource',
    }

    def __init__(self):
        self._clear_mappings()
        self._validate_headers = True

    @property
    def validate_headers(self) -> bool:
        return self._validate_headers

    @validate_headers.setter
    def validate_headers(self, value: bool):
        if not isinstance(value, bool):
            raise ValueError('validate_headers must be a boolean value')

    def _clear_mappings(self, include_providers: bool = True):
        """Reset all configured users/resources/acounts/addons and, optionally, providers."""
        if include_providers:
            # Mapping from _MockAddonProvider name to _MockAddonProvider
            self._known_providers: dict[str, _MockAddonProvider] = {}
        # Bidirectional mapping between user uri and mock "pk"
        self._known_users: dict[str, int] = {}
        # Bidirectional mapping between resource uri and mock "pk"
        self._known_resources: dict[str, int] = {}
        # Mapping from user "pk" to _MockAccounts for the user
        self._user_accounts: dict[str, list[_MockAccount]] = {}
        # Mapping from resource "pk" to _MockAddons "configured on" the resource
        self._resource_addons: dict[str, list[_MockAddon]] = {}

    def _get_or_create_user_entry(self, user: OsfUser):
        user_uri = user.get_semantic_iri()
        user_pk = self._known_users.get(user_uri)
        if not user_pk:
            user_pk = len(self._known_users) + 1
            self._known_users[user_uri] = user_pk
            self._known_users[user_pk] = user_uri
        return user_uri, user_pk

    def _get_or_create_resource_entry(self, resource: AbstractNode):
        resource_uri = resource.get_semantic_iri()
        resource_pk = self._known_resources.get(resource_uri)
        if not resource_pk:
            resource_pk = len(self._known_resources) + 1
            self._known_resources[resource_uri] = resource_pk
            self._known_resources[resource_pk] = resource_uri
        return resource_uri, resource_pk

    def configure_mock_provider(self, provider_name: str, **service_attrs):
        known_provider = self._known_providers.get(provider_name)
        provider_pk = known_provider.pk if known_provider else len(self._known_providers) + 1
        new_provider = _MockAddonProvider(
            name=provider_name,
            pk=provider_pk,
            **service_attrs
        )
        self._known_providers[provider_name] = new_provider
        return new_provider

    def configure_mock_account(self, user: OsfUser, addon_name: str, **account_attrs):
        user_uri, user_pk = self._get_or_create_user_entry(user)
        account_pk = _get_nested_count(self._user_accounts) + 1
        connected_addon = self._known_providers[addon_name]
        new_account = _MockAccount(
            pk=account_pk,
            owner_pk=user_pk,
            provider_pk=connected_addon.pk,
            **account_attrs
        )
        self._user_accounts.setdefault(user_uri, []).append(new_account)
        return new_account

    def configure_mock_addon(self, resource: AbstractNode, connected_account: _MockAccount, **config_attrs):
        resource_uri, resource_pk = self._get_or_create_resource_entry(resource)
        addon_pk = _get_nested_count(self._resource_addons) + 1
        new_addon = _MockAddon(
            pk=addon_pk,
            resource_pk=resource_pk,
            connected_account=connected_account,
            **config_attrs
        )
        self._resource_addons.setdefault(resource_uri, []).append(new_addon)
        return new_addon

    @contextlib.context_manager
    def run_mock(self):
        with responses.RequestsMock() as requests_mock:
            requests_mock.add_callback(
                responses.GET,
                re.compile(f'{settings.GRAVYVALET_URL}.*'),
                callback=self._route_request,
                content_type='application/json',
            )
            yield requests_mock

    def _route_request(self, request) -> tuple[int, dict, str]:
        if self.validate_headers:
            hmac.validate_signed_headers(request)
        for route_expr, routed_func_name in self.ROUTES.items():
            url_regex = re.compile(f'{settings.GRAVYVALET_URL}{route_expr}')
            route_match = url_regex.match(request.url)
            if route_match:
                func = getattr(self, routed_func_name)
                return func(**route_match.groupdict())

    def _get_user_response(
        self,
        pk: typing.Optional[str] = None,
        user_uri: typing.Optional[str] = None
    ) -> tuple[int, dict, str]:
        if not (pk or user_uri):
            raise ValueError('Must have either user PK or uri for lookup')

        # if passed the user_uri, call came through list endpoint with filter
        if user_uri:
            list_view = True
            pk = self._known_users[user_uri]
        else:
            list_view = False
            pk = int(pk)
            user_uri = self._known_users[pk]

        return _format_response(
            data=_MockUserReference(pk=pk, uri=user_uri),
            list_view=list_view
        )

    def _get_resource_response(
        self,
        pk: typing.Optional[str] = None,
        resource_uri: typing.Optional[str] = None
    ) -> tuple[int, dict, str]:
        if not (pk or resource_uri):
            raise ValueError('Must have either user PK or uri for lookup')

        # if passed the resource_uri, call came through list endpoint with filter
        if resource_uri:
            list_view = True
            pk = self._known_resources[resource_uri]
        else:
            list_view = False
            pk = int(pk)
            resource_uri = self._known_resources[pk]

        return _format_response(
            data=_MockResourceReference(pk=pk, uri=resource_uri),
            list_view=list_view
        )

    def _get_user_accounts(self, user_pk: str) -> tuple(int, dict, str):
        return _format_response(
            data=self._user_accounts.get(int(user_pk), []),
            list_view=True
        )

    def _get_resource_addons(self, resource_pk: str) -> tuple(int, dict, str):
        resource_pk = int(resource_pk)
        return _format_response(
            data=self._resource_addons.get(int(resource_pk), []),
            list_view=True
        )


def _format_response(
    data: typing.Union[_MockGVEntity, list[_MockGVEntity]],
    status_code: int = 200,
    list_view: bool = False,
    headers: typing.Optional[dict] = None
) -> tuple(int, dict, str):
    """Returns the expected (status, headers, json) tuple expected by callbacks for MockRequest."""
    headers = headers or {}
    if list_view and not isinstance(data, list):
        data = list[data]
    response_dict = {
        data: data.serialize() if not list_view else [entry.serialize() for entry in data]
    }
    return (status_code, headers, json.dumps(response_dict))


def _get_nested_count(d: dict[typing.ANY, list[typing.ANY]]):
    """Get the total number of entries from a dictionary with lists for values."""
    return sum(map(len, itertools.chain(d.values())))
