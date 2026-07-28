Graph API Version

[v25.0](#)

# Insights

# Insights Result

This page contains the query result of object/insights endpoint.

## Reading

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  token with structure: ID | ID of the insight. |
| `description`  string | The full description of the metric.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | Name of the metric.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `period`  enum | Length of the period during which the insights were collected.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `title`  string | The title of the metric.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `values`  [list<InsightsValue>](https://developers.facebook.com/docs/graph-api/reference/insights-value/) | Individual data points for the insight grouped by different time periods (determined by period).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
