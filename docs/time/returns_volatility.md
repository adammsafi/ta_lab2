# returns_volatility

## Windows
- Rolling returns use tf_days_nominal
- Volatility windows use tf_days_nominal
- Calendar windows use *_CAL anchors

## Diagram

```
tf_day -----> rolling window N days
_CAL  -----> window between anchor boundaries
```
