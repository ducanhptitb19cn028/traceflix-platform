"""
Thin producer/consumer abstraction over Kafka, with an in-process fallback.

``get_bus()`` returns a real Kafka-backed bus when ``kafka-python`` is installed
*and* a broker at ``TF_KAFKA_BOOTSTRAP`` is reachable; otherwise it returns an
``InMemoryBus`` that routes messages through per-topic ``deque``s in the same
process. This keeps the whole backbone runnable in a single pytest with no Docker
-- the same "works offline by default" contract as collectors/telemetry.py.

Interface (deliberately minimal):
    bus.produce(topic, key, value_bytes)
    for key, value in bus.consume(topic, group, timeout): ...
    bus.flush()
"""
from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Iterator

BOOTSTRAP = os.getenv("TF_KAFKA_BOOTSTRAP", "")   # e.g. "localhost:9092"


class InMemoryBus:
    """Single-process pub/sub. Each (topic, group) keeps an independent cursor so
    the detector and the LLM can both consume the same topic at their own pace."""

    def __init__(self) -> None:
        self._log: dict[str, list[tuple[bytes, bytes]]] = defaultdict(list)
        self._cursor: dict[tuple[str, str], int] = defaultdict(int)
        self.backend = "memory"

    def produce(self, topic: str, key: str, value: bytes) -> None:
        self._log[topic].append((key.encode("utf-8"), value))

    def consume(self, topic: str, group: str = "default",
                timeout: float = 0.0) -> Iterator[tuple[str, bytes]]:
        """Yield all messages not yet seen by this group, then return. (Batch
        semantics -- the orchestrator calls it in a loop; no long-poll needed.)"""
        log = self._log[topic]
        i = self._cursor[(topic, group)]
        while i < len(log):
            k, v = log[i]
            i += 1
            yield k.decode("utf-8"), v
        self._cursor[(topic, group)] = i

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class KafkaBus:
    """kafka-python backed bus. Producers/consumers are created lazily per topic."""

    def __init__(self, bootstrap: str) -> None:
        from kafka import KafkaConsumer, KafkaProducer  # noqa: F401

        self._KafkaConsumer = KafkaConsumer
        self.bootstrap = bootstrap
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            acks="all", linger_ms=20, retries=3,
        )
        self._consumers: dict[tuple[str, str], object] = {}
        self.backend = "kafka"

    def produce(self, topic: str, key: str, value: bytes) -> None:
        self._producer.send(topic, key=key.encode("utf-8"), value=value)

    def consume(self, topic: str, group: str = "default",
                timeout: float = 1.0) -> Iterator[tuple[str, bytes]]:
        c = self._consumers.get((topic, group))
        if c is None:
            c = self._KafkaConsumer(
                topic, bootstrap_servers=self.bootstrap, group_id=group,
                auto_offset_reset="earliest", enable_auto_commit=True,
                consumer_timeout_ms=int(timeout * 1000),
            )
            self._consumers[(topic, group)] = c
        for msg in c:
            yield (msg.key.decode("utf-8") if msg.key else ""), msg.value

    def flush(self) -> None:
        self._producer.flush()

    def close(self) -> None:
        self._producer.close()
        for c in self._consumers.values():
            c.close()  # type: ignore[attr-defined]


_SHARED: object | None = None


def get_bus(shared: bool = True) -> InMemoryBus | KafkaBus:
    """Return a Kafka bus if a broker is configured & reachable, else in-memory.

    ``shared=True`` returns a process-wide singleton so that an in-memory run of
    producer+consumers in one process actually sees each other's messages."""
    global _SHARED
    if shared and _SHARED is not None:
        return _SHARED  # type: ignore[return-value]

    bus: InMemoryBus | KafkaBus
    if BOOTSTRAP:
        try:
            bus = KafkaBus(BOOTSTRAP)
        except Exception as e:  # missing lib or unreachable broker
            print(f"[bus] Kafka unavailable ({e!r}); falling back to in-memory bus")
            bus = InMemoryBus()
    else:
        bus = InMemoryBus()

    if shared:
        _SHARED = bus
    return bus
