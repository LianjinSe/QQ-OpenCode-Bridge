from pathlib import Path
from types import SimpleNamespace

import pytest

from qqbot.bridge import Bridge


@pytest.mark.asyncio
async def test_close_attempts_every_component_after_one_close_fails():
    closed = []

    class Resource:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        async def close(self):
            closed.append(self.name)
            if self.fail:
                raise RuntimeError("close failed")

    bridge = object.__new__(Bridge)
    bridge.webui = Resource("webui", fail=True)
    bridge.delivery_tools = Resource("delivery")
    bridge.napcat_tools = Resource("napcat")
    bridge.knowledge = Resource("knowledge")
    bridge.memory = Resource("memory")
    bridge.onebot = SimpleNamespace(disconnect=lambda: _disconnect(closed))

    await bridge.close()

    assert closed == ["webui", "delivery", "napcat", "knowledge", "memory", "onebot"]


async def _disconnect(closed):
    closed.append("onebot")


def test_partial_component_assembly_closes_open_store(monkeypatch, tmp_path):
    from qqbot import bridge as bridge_module
    from qqbot.napcat_tools import NapCatTools

    closed = []
    napcat_instances = []

    class OpenStore:
        def close(self):
            closed.append("memory-store")
            raise RuntimeError("store close failed")

    class Memory:
        def __init__(self, *args, **kwargs):
            self.store = OpenStore()

    class Knowledge:
        def __init__(self, *args, **kwargs):
            self.store = None

    def make_napcat(*args, **kwargs):
        instance = NapCatTools(*args, **kwargs)
        napcat_instances.append(instance)
        return instance

    def broken_delivery(*args, **kwargs):
        raise RuntimeError("delivery initialization failed")

    monkeypatch.setattr(bridge_module, "PersonalMemory", Memory)
    monkeypatch.setattr(bridge_module, "Knowledge", Knowledge)
    monkeypatch.setattr(bridge_module, "NapCatTools", make_napcat)
    monkeypatch.setattr(bridge_module, "DeliveryTools", broken_delivery)
    config = SimpleNamespace(state_db=Path(tmp_path / "state.sqlite"), napcat_tools_enabled=True)

    with pytest.raises(RuntimeError, match="delivery initialization failed"):
        Bridge(config, object(), object(), object())

    assert closed == ["memory-store"]
    assert len(napcat_instances) == 1
    assert napcat_instances[0].db is None
