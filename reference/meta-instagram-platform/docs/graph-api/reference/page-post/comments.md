Graph API Version

[v25.0](#)

# Page Post Comments

## Reading

Get comments on a Page post.

The `id` field for the `/PAGEPOST-ID/comments` endpoint will no longer be returned for apps using the [Page Public Content Access feature](https://developers.facebook.com/docs/pages/overview/permissions-features#features). To access the `id` field for comments for a Page post you must be able to perform the [MODERATE task](https://developers.facebook.com/docs/pages/overview/permissions-features#tasks) on the Page being queried. This change is in effect for v11.0+ and will be implement for all versions on September, 7, 2021.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

Send a `GET` request to the `/{page-post-id}/comments` edge:

curl -i -X GET "https://graph.facebook.com/{page-post-id}/comments&access\_token={page-access-token}"

### Limitations

* Read-after-write may be delayed for video or GIF comments. Retry any failed queries.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `filter`  enum{stream, toplevel} | Default value: `toplevel`  SELF\_EXPLANATORY |
| `live_filter`  enum{filter\_low\_quality, no\_filter} | Default value: `filter_low_quality`  For comments on a Live streaming video, this determines whether low quality comments will be filtered out of the results (filtering is enabled by default). In all other circumstances this parameter is ignored. |
| `order`  enum{chronological, reverse\_chronological} | Preferred ordering of the comments. Accepts chronological (oldest first) and reverse chronological (newest first). If the comments can be ranked, then the order will always be ranked regardless of this modifier. The best practice for querying comments on a Live video is to continually poll for comments in the reversechronological ordering mode. |
| `since`  datetime | Lower bound of the time range to consider |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {},
    "summary": {}
}
```

#### `data`

A list of [Comment](/docs/graph-api/reference/comment/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=order`).

| Field | Description |
| --- | --- |
| `order`  enum | Preferred ordering of the comments. Accepts chronological (oldest first) and reverse chronological (newest first). If the comments can be ranked, then the order will always be ranked regardless of this modifier. The best practice for querying comments on a Live video is to continually poll for comments in the reversechronological ordering mode. |
| `total_count`  unsigned int32 | Total number of people who commented |
| `can_comment`  bool | Can the viewer comment |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 104 | Incorrect signature |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 210 | User not visible |
| 2500 | Error parsing graph query |
| 613 | Calls to this api have exceeded the rate limit. |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
