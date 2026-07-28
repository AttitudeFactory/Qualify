Graph API Version

[v25.0](#)

# Ad Set Copies

Create a duplicate ad set based on an existing one.

The Marketing API has it is own rate limiting logic. If you are encountering errors mentioning a reached limit, see [Rate Limiting](/docs/marketing-apis/rate-limiting).

## Reading

Endpoint to read the copies of an Ad Set.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bad-set-id%7D%2Fcopies&version=v25.0)

```
GET /v25.0/{ad-set-id}/copies HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{ad-set-id}/copies',
    '{access-token}'
  );
} catch(Facebook\Exceptions\FacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(Facebook\Exceptions\FacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
/* handle the result */
```

```
/* make the API call */
FB.api(
    "/{ad-set-id}/copies",
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{ad-set-id}/copies",
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{ad-set-id}/copies"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | Preset date range used to aggregate insights metrics |
| `effective_status`  list<enum{ACTIVE, PAUSED, DELETED, PENDING\_REVIEW, DISAPPROVED, PREAPPROVED, PENDING\_BILLING\_INFO, CAMPAIGN\_PAUSED, ARCHIVED, ADSET\_PAUSED, IN\_PROCESS, WITH\_ISSUES}> | Filter adsets by effective status |
| `is_completed`  boolean | Filter adsets by completed status |
| `time_range`  {'since':YYYY-MM-DD,'until':YYYY-MM-DD} | Time range used to aggregate insights metrics |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |

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

A list of [AdSet](/docs/graph-api/reference/ad-campaign/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=insights`).

| Field | Description |
| --- | --- |
| `insights`  Edge<AdsInsights> | Analytics summary for all objects |
| `total_count`  unsigned int32 | Total number of objects  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

If you are copying an adset that already finished, the copy will be scheduled to start at the creation's time with the same duration of the original adset.

### Asynchronous

This endpoint supports [asynchronous batch requests](/docs/graph-api/asynchronous-batch-requests), which enables you to send up to 50 requests in a single HTTP request. If you want to copy large amount of objects, you should use asynchronous batch request. To do so, set `deep_copy` to `true`, and you can copy the adset and all of its ads in one sub-request. For example if you have two adsets and each of them has 50 ads, you can copy 2 adsets and all their ads:

```
curl -F 'access_token=...'\
-F 'asyncbatch=[{ "method":"POST", "relative_url":"<ad-set-id>/copies","name":"async_copy1", body":"name=copy_adset_1&deep_copy=true" },{ "method":"POST", "relative_url":"<ad-set-id>/copies","name":"async_copy2", body": "name=copy_adset_2&deep_copy=true"}]' \
https://graph.facebook.com/<VERSION>
```

### Targeting DSA Regulated Locations (European Union)

To copy an ad set targeted in the European Union's Digital Services Act (DSA) regulated locations, please set the payor/beneficiary information first. Otherwise the copying request may respond with one of the following errors:


**Payor missing error**

```
{
  "error": {
    "message": "Invalid parameter",
    "type": "FacebookApiException",
    "code": 100,
    "error_data": "{\"blame_field_specs\":[[\"dsa_payor\"]]}",
    "error_subcode": 3858079,
    "is_transient": false,
    "error_user_title": "No payor provided in DSA regulated region",
    "error_user_msg": "The DSA requires ads to provide payor information in regulated regions. Updating/creating ad needs to provide payor of the ad.",
    "fbtrace_id": "fbtrace_id"
  },
  "__fb_trace_id__": "fbtrace_id",
  "__www_request_id__": "request_id"
}
```

**Beneficiary missing error**

```
{
  "error": {
    "message": "Invalid parameter",
    "type": "FacebookApiException",
    "code": 100,
    "error_data": "{\"blame_field_specs\":[[\"dsa_beneficiary\"]]}",
    "error_subcode": 3858081,
    "is_transient": false,
    "error_user_title": "No payor/beneficiary provided in DSA regulated location",
    "error_user_msg": "The DSA requires ads to provide beneficiary information in regulated regions. Updating/creating ad needs to provide beneficiary of the ad.",
    "fbtrace_id": "fbtrace_id"
  },
  "__fb_trace_id__": "fbtrace_id",
  "__www_request_id__": "request_id"
}
```

You can make a POST request to `copies` edge from the following paths:

* [`/{ad_set_id}/copies`](/docs/graph-api/reference/ad-campaign/copies/)

When posting to this edge, an [AdSet](/docs/graph-api/reference/ad-campaign/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `campaign_id`  numeric string or integer | Single ID of a campaign to make parent of the copy. The copy inherits all campaign settings, such as budget from the parent.Ignore if you want to keep the copy under the original campaign parent. |
| `deep_copy`  boolean | Default value: `false`  Whether to copy all the child ads. Limits: the total number of children ads to copy should not exceed 3 for a synchronous call and 51 for an asynchronous call. |
| `end_time`  datetime | The end time of the set, e.g. `2015-03-12 23:59:59-07:00` or `2015-03-12 23:59:59 PDT`. UTC UNIX timestamp. When creating a set with a daily budget, specify `end_time=0` to set the set to be ongoing without end date. If not set, the copied adset will inherit the end time from the original set |
| `rename_options`  JSON or object-like arrays | Rename options |
| `rename_strategy`  enum {DEEP\_RENAME, ONLY\_TOP\_LEVEL\_RENAME, NO\_RENAME} | Default value: `ONLY_TOP_LEVEL_RENAME`  `DEEP_RENAME`: will change this object's name and children's names in the copied object. `ONLY_TOP_LEVEL_RENAME`: will change the this object's name but won't change the children's name in the copied object. `NO_RENAME`: will change no name in the copied object |
| `rename_prefix`  string | A prefix to copy names. Defaults to null if not provided. |
| `rename_suffix`  string | A suffix to copy names. Defaults to null if not provided and appends a localized string of `- Copy` based on the ad account locale. |
| `start_time`  datetime | The start time of the set, e.g. `2015-03-12 23:59:59-07:00` or `2015-03-12 23:59:59 PDT`. UTC UNIX timestamp. If not set, the copied adset will inherit the start time from the original set |
| `status_option`  enum {ACTIVE, PAUSED, INHERITED\_FROM\_SOURCE} | Default value: `PAUSED`  `ACTIVE`: the copied adset will have active status. `PAUSED`: the copied adset will have paused status. `INHERITED_FROM_SOURCE`: the copied adset will have the status from the original set. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `copied_adset_id` in the return type.

Struct {

`copied_adset_id`: numeric string,

`ad_object_ids`: List [

Struct {

`ad_object_type`: enum {unique\_adcreative, ad, ad\_set, campaign, opportunities, privacy\_info\_center, topline, ad\_account, product},

`source_id`: numeric string,

`copied_id`: numeric string,

}

],

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 2695 | The ad set creation reached its campaign group(ios14) limit. |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
