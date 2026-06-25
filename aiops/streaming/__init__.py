"""
Kafka event backbone for TraceFlix-AIOps.

Three topics carry the pipeline:

    tf.telemetry.windows  -- raw MELT windows (producer_collector)
    tf.anomalies          -- OnlineModel verdicts (consumer_detector)
    tf.incidents          -- LLM fault reasoning (consumer_llm)

Everything runs without a broker: ``bus.get_bus()`` falls back to an in-process
queue when kafka-python or a broker is absent, the same way the collectors fall
back to synthetic data. See docs/KAFKA_LLM_ARCHITECTURE.md.
"""
