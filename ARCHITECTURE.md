# Project Tree

src/
├── __main__.py
│
├── brokers/
│   ├── mt5.py
│   └── mt5_components/
│       ├── connector.py
│       ├── data_fetcher.py
│       ├── order_executor.py
│       ├── position_repository.py
│       └── retcode_mapper.py
│
├── config/
│   └── loader.py
│
├── domain/
│   ├── analytics.py
│   ├── enums.py
│   ├── exceptions.py
│   ├── market_data.py
│   └── trading.py
│
├── engine/
│   ├── forward.py
│   └── components/
│       ├── data_handler.py
│       ├── entry_handler.py
│       ├── exit_handler.py
│       ├── position_manager.py
│       ├── risk_manager.py
│       ├── trading_config.py
│       └── warmup.py
│
├── indicators/
│   ├── base.py
│   └── volatility.py
│
├── infrastructure/
│   ├── logger/
│   │   ├── data_logger.py
│   │   ├── heartbeat.py
│   │   └── logger.py
│   │
│   ├── notifier/
│   │   └── line_notifier.py
│   │
│   └── state/
│       └── position_storage.py
│
├── strategies/
│   ├── base.py
│   ├── registry.py
│   ├── strategy_loader.py
│   │
│   └── bb_squeeze/
│       ├── config.py
│       └── signal.py