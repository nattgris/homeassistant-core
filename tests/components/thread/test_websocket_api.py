"""Test the thread websocket API."""

from unittest.mock import ANY, AsyncMock

from zeroconf.asyncio import AsyncServiceInfo

from homeassistant.components.thread import dataset_store, discovery
from homeassistant.components.thread.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from . import (
    DATASET_1,
    DATASET_2,
    DATASET_3,
    ROUTER_DISCOVERY_GOOGLE_1,
    ROUTER_DISCOVERY_HASS,
)

from tests.typing import WebSocketGenerator


async def test_add_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test we can add a dataset."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": "thread/add_dataset_tlv", "source": "test", "tlv": DATASET_1}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] is None

    store = await dataset_store.async_get_store(hass)
    assert len(store.datasets) == 1
    dataset = next(iter(store.datasets.values()))
    assert dataset.source == "test"
    assert dataset.tlv == DATASET_1


async def test_add_invalid_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test adding an invalid dataset."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": "thread/add_dataset_tlv", "source": "test", "tlv": "DEADBEEF"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {"code": "invalid_format", "message": "unknown type 222"}


async def test_delete_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test we can delete a dataset."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "thread/add_dataset_tlv", "source": "test", "tlv": DATASET_1}
    )
    msg = await client.receive_json()
    assert msg["success"]

    await client.send_json_auto_id(
        {"type": "thread/add_dataset_tlv", "source": "test", "tlv": DATASET_2}
    )
    msg = await client.receive_json()
    assert msg["success"]

    await client.send_json_auto_id({"type": "thread/list_datasets"})
    msg = await client.receive_json()
    assert msg["success"]
    datasets = msg["result"]["datasets"]

    # Try deleting the preferred dataset
    await client.send_json_auto_id(
        {"type": "thread/delete_dataset", "dataset_id": datasets[0]["dataset_id"]}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {
        "code": "not_allowed",
        "message": "attempt to remove preferred dataset",
    }

    # Try deleting a non preferred dataset
    await client.send_json_auto_id(
        {"type": "thread/delete_dataset", "dataset_id": datasets[1]["dataset_id"]}
    )
    msg = await client.receive_json()
    assert msg["success"]

    # Try deleting the same dataset again
    await client.send_json_auto_id(
        {"type": "thread/delete_dataset", "dataset_id": datasets[1]["dataset_id"]}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {
        "code": "not_found",
        "message": f"'{datasets[1]['dataset_id']}'",
    }


async def test_list_get_dataset(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test list and get datasets."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)

    await client.send_json({"id": 1, "type": "thread/list_datasets"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"datasets": []}

    datasets = [
        {"source": "Google", "tlv": DATASET_1},
        {"source": "Multipan", "tlv": DATASET_2},
        {"source": "🎅", "tlv": DATASET_3},
    ]
    for dataset in datasets:
        await dataset_store.async_add_dataset(hass, dataset["source"], dataset["tlv"])

    store = await dataset_store.async_get_store(hass)
    for dataset in store.datasets.values():
        if dataset.source == "Google":
            dataset_1 = dataset
        if dataset.source == "Multipan":
            dataset_2 = dataset
        if dataset.source == "🎅":
            dataset_3 = dataset

    await client.send_json({"id": 2, "type": "thread/list_datasets"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {
        "datasets": [
            {
                "created": dataset_1.created.isoformat(),
                "dataset_id": dataset_1.id,
                "extended_pan_id": "1111111122222222",
                "network_name": "OpenThreadDemo",
                "pan_id": "1234",
                "preferred": True,
                "source": "Google",
            },
            {
                "created": dataset_2.created.isoformat(),
                "dataset_id": dataset_2.id,
                "extended_pan_id": "1111111122222222",
                "network_name": "HomeAssistant!",
                "pan_id": "1234",
                "preferred": False,
                "source": "Multipan",
            },
            {
                "created": dataset_3.created.isoformat(),
                "dataset_id": dataset_3.id,
                "extended_pan_id": "1111111122222222",
                "network_name": "~🐣🐥🐤~",
                "pan_id": "1234",
                "preferred": False,
                "source": "🎅",
            },
        ]
    }

    await client.send_json(
        {"id": 3, "type": "thread/get_dataset_tlv", "dataset_id": dataset_2.id}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"tlv": dataset_2.tlv}

    await client.send_json(
        {"id": 4, "type": "thread/get_dataset_tlv", "dataset_id": "blah"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {"code": "not_found", "message": "unknown dataset"}


async def test_discover_routers(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_async_zeroconf: None
) -> None:
    """Test discovering thread routers."""
    mock_async_zeroconf.async_add_service_listener = AsyncMock()
    mock_async_zeroconf.async_remove_service_listener = AsyncMock()
    mock_async_zeroconf.async_get_service_info = AsyncMock()

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)

    # Subscribe
    await client.send_json({"id": 1, "type": "thread/discover_routers"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] is None

    mock_async_zeroconf.async_add_service_listener.assert_called_once_with(
        "_meshcop._udp.local.", ANY
    )
    listener: discovery.ThreadRouterDiscovery.ThreadServiceListener = (
        mock_async_zeroconf.async_add_service_listener.mock_calls[0][1][1]
    )

    # Discover a service
    mock_async_zeroconf.async_get_service_info.return_value = AsyncServiceInfo(
        **ROUTER_DISCOVERY_HASS
    )
    listener.add_service(
        None, ROUTER_DISCOVERY_HASS["type_"], ROUTER_DISCOVERY_HASS["name"]
    )
    msg = await client.receive_json()
    assert msg == {
        "event": {
            "data": {
                "brand": "homeassistant",
                "extended_pan_id": "e60fc7c186212ce5",
                "model_name": "OpenThreadBorderRouter",
                "network_name": "OpenThread HC",
                "server": "core-silabs-multiprotocol.local.",
                "vendor_name": "HomeAssistant",
            },
            "key": "aeeb2f594b570bbf",
            "type": "router_discovered",
        },
        "id": 1,
        "type": "event",
    }

    # Discover another service - we don't care if zeroconf considers this an update
    mock_async_zeroconf.async_get_service_info.return_value = AsyncServiceInfo(
        **ROUTER_DISCOVERY_GOOGLE_1
    )
    listener.update_service(
        None, ROUTER_DISCOVERY_GOOGLE_1["type_"], ROUTER_DISCOVERY_GOOGLE_1["name"]
    )
    msg = await client.receive_json()
    assert msg == {
        "event": {
            "data": {
                "brand": "google",
                "extended_pan_id": "9e75e256f61409a3",
                "model_name": "Google Nest Hub",
                "network_name": "NEST-PAN-E1AF",
                "server": "2d99f293-cd8e-2770-8dd2-6675de9fa000.local.",
                "vendor_name": "Google Inc.",
            },
            "key": "f6a99b425a67abed",
            "type": "router_discovered",
        },
        "id": 1,
        "type": "event",
    }

    # Remove a service
    listener.remove_service(
        None, ROUTER_DISCOVERY_HASS["type_"], ROUTER_DISCOVERY_HASS["name"]
    )
    msg = await client.receive_json()
    assert msg == {
        "event": {"key": "aeeb2f594b570bbf", "type": "router_removed"},
        "id": 1,
        "type": "event",
    }

    # Unsubscribe
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    response = await client.receive_json()
    assert response["success"]

    mock_async_zeroconf.async_remove_service_listener.assert_called_once_with(listener)
