Graph API Version

[v25.0](#)

# Page Nlp Configs

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `nlp_configs` edge from the following paths:

* [`/{page_id}/nlp_configs`](/docs/graph-api/reference/page/nlp_configs/)

When posting to this edge, a [Page](/docs/graph-api/reference/page/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `api_version`  enum {} | api\_version |
| `custom_token`  string | An optional Wit token enable custom entities |
| `model`  enum {ARABIC, CHINESE, CROATIAN, CUSTOM, DANISH, DUTCH, ENGLISH, FRENCH\_STANDARD, GEORGIAN, GERMAN\_STANDARD, GREEK, HEBREW, HUNGARIAN, IRISH, ITALIAN\_STANDARD, KOREAN, NORWEGIAN\_BOKMAL, POLISH, PORTUGUESE, ROMANIAN, SPANISH, SWEDISH, VIETNAMESE} | An option for which model to use in production. |
| `n_best`  int64 | The number of intents and traits to return, other than the best one. |
| `nlp_enabled`  boolean | A boolean to enable/disable Built-In NLP. |
| `other_language_support`  JSON object {string : JSON object} | A map of language to model type and Wit token for language identification. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 80006 | There have been too many messenger api calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
