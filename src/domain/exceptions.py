class MarketDataUnavailable(Exception):
    pass

class TickFetchError(MarketDataUnavailable):
    pass

class RateFetchError(MarketDataUnavailable):
    pass