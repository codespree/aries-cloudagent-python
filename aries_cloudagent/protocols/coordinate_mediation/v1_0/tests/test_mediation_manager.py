"""Test MediationManager."""
import logging

import pytest

from aries_cloudagent.connections.models.conn_record import ConnRecord
from aries_cloudagent.messaging.request_context import RequestContext
from aries_cloudagent.transport.inbound.receipt import MessageReceipt

from ....routing.v1_0.models.route_record import RouteRecord
from ..manager import (
    MediationAlreadyExists,
    MediationManager,
    MediationManagerError,
    MediationNotGrantedError,
)
from ..messages.inner.keylist_update_rule import KeylistUpdateRule
from ..messages.inner.keylist_updated import KeylistUpdated
from ..messages.mediate_deny import MediationDeny
from ..messages.mediate_grant import MediationGrant
from ..messages.mediate_request import MediationRequest
from ..models.mediation_record import MediationRecord

TEST_CONN_ID = "conn-id"
TEST_ENDPOINT = "https://example.com"
TEST_VERKEY = "3Dn1SJNPaCXcvvJvSbsFWP2xaCjMom3can8CQNhWrTRx"
TEST_ROUTE_VERKEY = "9WCgWKUaAJj3VWxxtzvvMQN3AoFxoBtBDo9ntwJnVVCC"


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def session():
    """Fixture for session used in tests."""
    # pylint: disable=W0621
    context = RequestContext.test_context()
    context.message_receipt = MessageReceipt(sender_verkey=TEST_VERKEY)
    context.connection_record = ConnRecord(connection_id=TEST_CONN_ID)
    yield await context.session()


@pytest.fixture
async def manager(session):  # pylint: disable=W0621
    """Fixture for manager used in tests."""
    yield MediationManager(session)


@pytest.fixture
def record():
    """Fixture for record used in tets."""
    yield MediationRecord(
        state=MediationRecord.STATE_GRANTED, connection_id=TEST_CONN_ID
    )


class TestMediationManager:  # pylint: disable=R0904,W0621
    """Test MediationManager."""

    async def test_create_manager_no_session(self):
        """test_create_manager_no_session."""
        with pytest.raises(MediationManagerError):
            await MediationManager(None)

    async def test_create_did(self, manager):
        """test_create_did."""
        # pylint: disable=W0212
        await manager._create_routing_did()
        assert await manager._retrieve_routing_did()

    async def test_retrieve_did_when_absent(self, manager):
        """test_retrieve_did_when_absent."""
        # pylint: disable=W0212
        assert await manager._retrieve_routing_did() is None

    async def test_receive_request_no_terms(self, manager):
        """test_receive_request_no_terms."""
        request = MediationRequest()
        record = await manager.receive_request(TEST_CONN_ID, request)
        assert record.connection_id == TEST_CONN_ID

    async def test_receive_request_record_exists(self, session, manager):
        """test_receive_request_no_terms."""
        request = MediationRequest()
        await MediationRecord(connection_id=TEST_CONN_ID).save(session)
        with pytest.raises(MediationAlreadyExists):
            await manager.receive_request(TEST_CONN_ID, request)

    @pytest.mark.skip(
        reason="mediator and recipient terms are only loosely defined in RFC 0211"
    )
    async def test_receive_request_unacceptable_terms(self):
        """test_receive_request_unacceptable_terms."""

    async def test_grant_request(self, session, manager):
        """test_grant_request."""
        # pylint: disable=W0212
        request = MediationRequest()
        record = await manager.receive_request(TEST_CONN_ID, request)
        assert record.connection_id == TEST_CONN_ID
        grant = await manager.grant_request(record)
        assert grant.endpoint == session.settings.get("default_endpoint")
        assert grant.routing_keys == [(await manager._retrieve_routing_did()).verkey]

    async def test_deny_request(self, manager):
        """test_deny_request."""
        request = MediationRequest()
        record = await manager.receive_request(TEST_CONN_ID, request)
        assert record.connection_id == TEST_CONN_ID
        deny = await manager.deny_request(record)
        assert deny.mediator_terms == []
        assert deny.recipient_terms == []

    async def test_update_keylist_delete(self, session, manager, record):
        """test_update_keylist_delete."""
        await RouteRecord(connection_id=TEST_CONN_ID, recipient_key=TEST_VERKEY).save(
            session
        )
        response = await manager.update_keylist(
            record=record,
            updates=[
                KeylistUpdateRule(
                    recipient_key=TEST_VERKEY, action=KeylistUpdateRule.RULE_REMOVE
                )
            ],
        )
        results = response.updated
        assert len(results) == 1
        assert results[0].recipient_key == TEST_VERKEY
        assert results[0].action == KeylistUpdateRule.RULE_REMOVE
        assert results[0].result == KeylistUpdated.RESULT_SUCCESS

    async def test_update_keylist_create(self, manager, record):
        """test_update_keylist_create."""
        response = await manager.update_keylist(
            record=record,
            updates=[
                KeylistUpdateRule(
                    recipient_key=TEST_VERKEY, action=KeylistUpdateRule.RULE_ADD
                )
            ],
        )
        results = response.updated
        assert len(results) == 1
        assert results[0].recipient_key == TEST_VERKEY
        assert results[0].action == KeylistUpdateRule.RULE_ADD
        assert results[0].result == KeylistUpdated.RESULT_SUCCESS

    async def test_update_keylist_create_existing(self, session, manager, record):
        """test_update_keylist_create_existing."""
        await RouteRecord(connection_id=TEST_CONN_ID, recipient_key=TEST_VERKEY).save(
            session
        )
        response = await manager.update_keylist(
            record=record,
            updates=[
                KeylistUpdateRule(
                    recipient_key=TEST_VERKEY, action=KeylistUpdateRule.RULE_ADD
                )
            ],
        )
        results = response.updated
        assert len(results) == 1
        assert results[0].recipient_key == TEST_VERKEY
        assert results[0].action == KeylistUpdateRule.RULE_ADD
        assert results[0].result == KeylistUpdated.RESULT_NO_CHANGE

    async def test_get_keylist(self, session, manager, record):
        """test_get_keylist."""
        await RouteRecord(connection_id=TEST_CONN_ID, recipient_key=TEST_VERKEY).save(
            session
        )
        # Non-server route for verifying filtering
        await RouteRecord(
            role=RouteRecord.ROLE_CLIENT,
            connection_id=TEST_CONN_ID,
            recipient_key=TEST_ROUTE_VERKEY,
        ).save(session)
        results = await manager.get_keylist(record)
        assert len(results) == 1
        assert results[0].connection_id == TEST_CONN_ID
        assert results[0].recipient_key == TEST_VERKEY

    async def test_gey_keylist_no_granted_record(self, manager):
        """test_gey_keylist_no_granted_record."""
        record = MediationRecord()
        with pytest.raises(MediationNotGrantedError):
            await manager.get_keylist(record)

    async def test_create_keylist_query_response(self, session, manager, record):
        """test_create_keylist_query_response."""
        await RouteRecord(connection_id=TEST_CONN_ID, recipient_key=TEST_VERKEY).save(
            session
        )
        results = await manager.get_keylist(record)
        response = await manager.create_keylist_query_response(results)
        assert len(response.keys) == 1
        assert response.keys[0].recipient_key
        response = await manager.create_keylist_query_response([])
        assert not response.keys

    async def test_prepare_request(self, manager):
        """test_prepare_request."""
        record, request = await manager.prepare_request(TEST_CONN_ID)
        assert record.connection_id == TEST_CONN_ID
        assert request

    async def test_request_granted(self, manager):
        """test_request_granted."""
        record, _ = await manager.prepare_request(TEST_CONN_ID)
        grant = MediationGrant(endpoint=TEST_ENDPOINT, routing_keys=[TEST_ROUTE_VERKEY])
        await manager.request_granted(record, grant)
        assert record.state == MediationRecord.STATE_GRANTED
        assert record.endpoint == TEST_ENDPOINT
        assert record.routing_keys == [TEST_ROUTE_VERKEY]

    async def test_request_denied(self, manager):
        """test_request_denied."""
        record, _ = await manager.prepare_request(TEST_CONN_ID)
        deny = MediationDeny()
        await manager.request_denied(record, deny)
        assert record.state == MediationRecord.STATE_DENIED

    @pytest.mark.skip(reason="Mediation terms are not well defined in RFC 0211")
    async def test_request_denied_counter_terms(self):
        """test_request_denied_counter_terms."""

    async def test_prepare_keylist_query(self, manager):
        """test_prepare_keylist_query."""
        query = await manager.prepare_keylist_query()
        assert query.paginate.limit == -1
        assert query.paginate.offset == 0

    async def test_prepare_keylist_query_pagination(self, manager):
        """test_prepare_keylist_query_pagination."""
        query = await manager.prepare_keylist_query(
            paginate_limit=10, paginate_offset=20
        )
        assert query.paginate.limit == 10
        assert query.paginate.offset == 20

    @pytest.mark.skip(reason="Filtering is not well defined in RFC 0211")
    async def test_prepare_keylist_query_filter(self):
        """test_prepare_keylist_query_filter."""

    async def test_add_key_no_message(self, manager):
        """test_add_key_no_message."""
        update = await manager.add_key(TEST_VERKEY)
        assert update.updates
        assert update.updates[0].action == KeylistUpdateRule.RULE_ADD

    async def test_add_key_accumulate_in_message(self, manager):
        """test_add_key_accumulate_in_message."""
        update = await manager.add_key(TEST_VERKEY)
        await manager.add_key(recipient_key=TEST_ROUTE_VERKEY, message=update)
        assert update.updates
        assert len(update.updates) == 2
        assert update.updates[0].action == KeylistUpdateRule.RULE_ADD
        assert update.updates[1].action == KeylistUpdateRule.RULE_ADD
        assert update.updates[0].recipient_key == TEST_VERKEY
        assert update.updates[1].recipient_key == TEST_ROUTE_VERKEY

    async def test_remove_key_no_message(self, manager):
        """test_remove_key_no_message."""
        update = await manager.remove_key(TEST_VERKEY)
        assert update.updates
        assert update.updates[0].action == KeylistUpdateRule.RULE_REMOVE

    async def test_remove_key_accumulate_in_message(self, manager):
        """test_remove_key_accumulate_in_message."""
        update = await manager.remove_key(TEST_VERKEY)
        await manager.remove_key(recipient_key=TEST_ROUTE_VERKEY, message=update)
        assert update.updates
        assert len(update.updates) == 2
        assert update.updates[0].action == KeylistUpdateRule.RULE_REMOVE
        assert update.updates[1].action == KeylistUpdateRule.RULE_REMOVE
        assert update.updates[0].recipient_key == TEST_VERKEY
        assert update.updates[1].recipient_key == TEST_ROUTE_VERKEY

    async def test_add_remove_key_mix(self, manager):
        """test_add_remove_key_mix."""
        update = await manager.add_key(TEST_VERKEY)
        await manager.remove_key(recipient_key=TEST_ROUTE_VERKEY, message=update)
        assert update.updates
        assert len(update.updates) == 2
        assert update.updates[0].action == KeylistUpdateRule.RULE_ADD
        assert update.updates[1].action == KeylistUpdateRule.RULE_REMOVE
        assert update.updates[0].recipient_key == TEST_VERKEY
        assert update.updates[1].recipient_key == TEST_ROUTE_VERKEY

    async def test_store_update_results(self, session, manager):
        """test_store_update_results."""
        await RouteRecord(
            role=RouteRecord.ROLE_CLIENT,
            connection_id=TEST_CONN_ID,
            recipient_key=TEST_VERKEY,
        ).save(session)
        results = [
            KeylistUpdated(
                recipient_key=TEST_ROUTE_VERKEY,
                action=KeylistUpdateRule.RULE_ADD,
                result=KeylistUpdated.RESULT_SUCCESS,
            ),
            KeylistUpdated(
                recipient_key=TEST_VERKEY,
                action=KeylistUpdateRule.RULE_REMOVE,
                result=KeylistUpdated.RESULT_SUCCESS,
            ),
        ]
        await manager.store_update_results(TEST_CONN_ID, results)
        routes = await RouteRecord.query(session)
        assert len(routes) == 1
        assert routes[0].recipient_key == TEST_ROUTE_VERKEY

    async def test_store_updated_results_errors(self, caplog, manager):
        """test_store_updated_results_errors."""
        caplog.set_level(logging.WARNING)
        results = [
            KeylistUpdated(
                recipient_key=TEST_VERKEY,
                action=KeylistUpdateRule.RULE_ADD,
                result=KeylistUpdated.RESULT_NO_CHANGE,
            ),
            KeylistUpdated(
                recipient_key=TEST_VERKEY,
                action=KeylistUpdateRule.RULE_REMOVE,
                result=KeylistUpdated.RESULT_SERVER_ERROR,
            ),
            KeylistUpdated(
                recipient_key=TEST_VERKEY,
                action=KeylistUpdateRule.RULE_REMOVE,
                result=KeylistUpdated.RESULT_CLIENT_ERROR,
            ),
        ]
        await manager.store_update_results(TEST_CONN_ID, results)
        assert "no_change" in caplog.text
        assert "client_error" in caplog.text
        assert "server_error" in caplog.text
        print(caplog.text)

    async def test_get_my_keylist(self, session, manager):
        """test_get_my_keylist."""
        await RouteRecord(
            role=RouteRecord.ROLE_CLIENT,
            connection_id=TEST_CONN_ID,
            recipient_key=TEST_VERKEY,
        ).save(session)
        # Non-client record to verify filtering
        await RouteRecord(
            role=RouteRecord.ROLE_SERVER,
            connection_id=TEST_CONN_ID,
            recipient_key=TEST_ROUTE_VERKEY,
        ).save(session)
        keylist = await manager.get_my_keylist(TEST_CONN_ID)
        assert keylist
        assert len(keylist) == 1
        assert keylist[0].connection_id == TEST_CONN_ID
        assert keylist[0].recipient_key == TEST_VERKEY
        assert keylist[0].role == RouteRecord.ROLE_CLIENT