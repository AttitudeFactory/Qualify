# Asynchronous and Batch Requests



Use asynchronous requests to create ads and send numerous ads requests without having to block. Either specify a URL to call after requests complete or check the status of the request. See [Ad reference](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup#create).

To manage ads, use [batched requests](https://developers.facebook.com/docs/reference/api/batch). Use them to perform some of the more common requests.

## Asynchronous requests &#123;#aoverview&#125;

For example, get the status of the asynchronous request set:

```
curl -G \
  -d &#039;fields=name,success_count,error_count,is_completed&#039; \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;
```

This returns the overall status for the async request set as a JSON object. Not all fields appear by default. If you want your query to include non-default fields, specify them in `fields`, such as `fields=id,owner_id,name,total_count,success_count,error_count,is_completed`.

| Name | Description |
| --- | --- |
| `id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;The `id` of current async request set. |
| `owner_id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;Which object owns this async request set. For async requests on ads, `owner_id` is the account id. |
| `name`&lt;br&gt;&lt;br&gt;type: string | **Shown by default.**&lt;br&gt;&lt;br&gt;Name of this async request set. |
| `is_completed`&lt;br&gt;&lt;br&gt;type: boolean | **Shown by default.**&lt;br&gt;&lt;br&gt;Indicates whether all async requests in this set are complete. |
| `total_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Total requests count of this request set. |
| `initial_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests not yet served. |
| `in_progress_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests in progress. |
| `success_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests finished and successful. |
| `error_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests finished and failed. |
| `canceled_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests canceled by user |
| `notification_uri`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Notification URI for this async request set. |
| `notification_mode`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Way to receive notification. Valid values include:&lt;br&gt;&lt;br&gt;- `OFF` – No notifications&lt;br&gt;- `ON_COMPLETE` – Send notification when whole set finished. |

After you get the overall status of the async request set, get details of each request:

```
curl -G \
  -d &#039;fields=id,status&#039; \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;/requests
```

This returns status and details of each request inside the async request set. For async ad creation, make one request to create one ad. The status param is used to filter requests by its own status and can be any combination of following values:

*  `initial` – Not processed yet.
*  `in_progress` – Request is processing
*  `success` – Request finished and succeeds.
*  `error` – Request finished and failed
*  `canceled` – Request canceled by user

The response is a JSON array with default fields. To include any non-default field, specify it in `fields`, such as `fields=id,scope_object_id,status,result,input,async_request_set`.

| Name | Description |
| --- | --- |
| `id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;Individual async request ID |
| `scope_object_id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;Parent id of object this request creates. If you create an ad, this is ad set ID for the new ad. |
| `status`&lt;br&gt;&lt;br&gt;type: string | **Shown by default.**&lt;br&gt;&lt;br&gt;Status of this async request. Options:&lt;br&gt;&lt;br&gt;- `Initial` – Not processed yet&lt;br&gt;- `In_progress` – Request is processing&lt;br&gt;- `Success` – Request finished and succeeds&lt;br&gt;- `Error` – Request finished and failed&lt;br&gt;- `Canceled` – Request is canceled by user |
| `result`&lt;br&gt;&lt;br&gt;type: array | **Not shown by default.**&lt;br&gt;&lt;br&gt;If request is finished, shows result of the request.  &lt;br&gt;On success, the result is the same as a&lt;br&gt;non-async request. For example, if you create an ad, the result for each request is the ID of the new ad.&lt;br&gt;For errors, it will be array of:&lt;br&gt;&lt;br&gt;- `error_code` – Error code returned&lt;br&gt;- `error_message` – Error message |
| `input`&lt;br&gt;&lt;br&gt;type: object | **Not shown by default.**&lt;br&gt;&lt;br&gt;Original input for this async request. If you create an ad, the input is `adgroup_spec`. |
| `async_request_set`&lt;br&gt;&lt;br&gt;type: object | **Not shown by default.**&lt;br&gt;&lt;br&gt;Async request set that contains this individual request. |

### Get request details

To get details of a specific async request, make this call:

```
curl -G \
  -d &#039;fields=id,status&#039; \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;/requests
```

This returns a JSON object with fields listed above.

### List request sets for an account

You can create multiple async ad request sets. To query all async ad request sets for an ad account:

```
curl -G \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/act_&lt;AD_ACCOUNT_ID&gt;/asyncadrequestsets
```

This returns a JSON array of async request set objects. Each object is the same
as specified in [async request set section](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-campaign/asyncadrequests). You can filter results with `is_completed`. If `is_completed=true`, you see only completed async request set.

### List requests for an ad set

You can make an async call to create ads in different ad sets. To get the status for each ad set, get all ad creation requests for one ad set:

```
curl -G \
  -d &#039;fields=id,status&#039; \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;AD_SET_ID&gt;/asyncadrequests
```

This returns a JSON array of async request objects. The status, fields filter, and async request fields are the same as `https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;REQUEST_SET_ID&gt;/requests` API.

### Update request sets

You can change `name`, `notification_uri` and `notification_mode` for an async request set.

```
curl \
  -F &#039;name=New Name&#039; \
  -F &#039;notification_mode=OFF&#039; \
  -F &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;
```

This returns `true` on successful update. You can only change `notification_uri` and `notification_mode` before the notification is sent.

### Cancel request

You can cancel an async request, but the request can only be cancelled if it is not processed yet.

```
curl -X DELETE \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_ID&gt;
```

Returns `true` on successful cancellation. You can also cancel unprocessed requests in the async request set:

```
curl -X DELETE \
  -d &#039;access_token=&lt;ACCESS_TOKEN&gt;&#039; \
  https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;
```

Returns `true` on successful cancellation.

### Async examples &#123;#examples&#125;

Getting status of a specific async request:

```
//pretty=true for command line readable output
curl -G \
-d &quot;id=6012384857989&quot; \
-d &quot;pretty=true&quot; \
-d &quot;access_token=_____&quot; \
&quot;https://graph.facebook.com/v25.0/&quot;
```

Return values:

```
&#123;
   &quot;id&quot;: &quot;6012384857989&quot;,
   &quot;owner_id&quot;: 12345,
   &quot;name&quot;: &quot;testasyncset&quot;,
   &quot;is_completed&quot;: true
&#125;
```

Get results of requests:

```
curl -G \
-d &quot;id=6012384857989&quot; \
-d &quot;pretty=true&quot; \
-d &quot;fields=result&quot; \
-d &quot;access_token=_____&quot; \
&quot;https://graph.facebook.com/v25.0/requests&quot;
```

Returns:

```
&#123;
   &quot;data&quot;: [
      &#123;
         &quot;result&quot;: &#123;
            &quot;id&quot;: &quot;6012384860989&quot;
         &#125;,
         &quot;id&quot;: &quot;6012384858389&quot;
      &#125;,
      &#123;
         &quot;result&quot;: &#123;
            &quot;id&quot;: &quot;6012384858789&quot;
         &#125;,
         &quot;id&quot;: &quot;6012384858189&quot;
      &#125;
   ],
   &quot;paging&quot;: &#123;
      &quot;cursors&quot;: &#123;
         &quot;after&quot;: &quot;___&quot;,
         &quot;before&quot;: &quot;___&quot;
      &#125;
   &#125;
&#125;
```

Get list of request sets for an ad account:

```
curl -G \
-d &quot;is_completed=1&quot; \
-d &quot;pretty=true&quot; \
-d &quot;access_token=___&quot; \
&quot;https://graph.facebook.com/v25.0/act_71597454/asyncadrequestsets&quot;
```

Returns:

```
&#123;
   &quot;data&quot;: [
      &#123;
         &quot;id&quot;: &quot;6012384253789&quot;,
         &quot;owner_id&quot;: 71597454,
         &quot;name&quot;: &quot;testasyncset&quot;,
         &quot;is_completed&quot;: true
      &#125;,
   ],
   &quot;paging&quot;: &#123;
      &quot;cursors&quot;: &#123;
         &quot;after&quot;: &quot;___&quot;,
         &quot;before&quot;: &quot;___&quot;
      &#125;
   &#125;
&#125;
```

Getting a list of requests for a campaign:

```
curl -G \
-d &quot;status=SUCCESS,ERROR&quot; \
-d &quot;pretty=true&quot; \
-d &quot;access_token=___&quot; \
&quot;https://graph.facebook.com/v25.0/6008248529789/asyncadrequests&quot;
```

Return values:

```
&#123;
   &quot;data&quot;: [
      &#123;
         &quot;id&quot;: &quot;6012384951789&quot;,
         &quot;scope_object_id&quot;: 6008248529789,
         &quot;status&quot;: &quot;SUCCESS&quot;
      &#125;,
   ],
   &quot;paging&quot;: &#123;
      &quot;cursors&quot;: &#123;
         &quot;after&quot;: &quot;___&quot;,
         &quot;before&quot;: &quot;___&quot;
      &#125;
   &#125;
&#125;
```

## Batch requests &#123;#boverview&#125;
With [batched requests](https://developers.facebook.com/docs/reference/api/batch), combine a number of Graph API calls into the one HTTP request. Marketing API splits this request into its constituent requests. Batched requests reduce the number of HTTP requests you send to the Marketing API. You can also make parallel batch requests using separate processing threads.

**Note:** Each [batched request](https://developers.facebook.com/docs/reference/api/batch) can contain a maximum of 50 requests. For [ad](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup) creation, include 10 or fewer [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup) per batch.

Batch requests for [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup), [adcreatives](https://developers.facebook.com/docs/reference/ads-api/adcreative), and [ad sets](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-campaign) are similar, so this guide doesn&#039;t discuss them separately. For more information, see [Graph API batch requests](https://developers.facebook.com/docs/reference/api/batch) and [ETags](#etags).

### Create ads &#123;#adgroup&#125;

You can provide adcreative and other ad objects in a batched request. For example, you can create three [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup) using one [adcreative](https://developers.facebook.com/docs/reference/ads-api/adcreative) and three different [targeting specs](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/advanced-targeting). Define your [Ad Creative](https://developers.facebook.com/docs/reference/ads-api/adcreative) first then reference it when you create each [ad](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup):

```
curl -F &#039;access_token=______&#039;
  -F &#039;test1=&#064;./test1.jpg&#039;
  -F &#039;batch=[
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;name&quot;: &quot;create_adimage&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/adimages&quot;,
              &quot;attached_files&quot;: &quot;test1&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;name&quot;: &quot;create_creative&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/adcreatives&quot;,
              &quot;attached_files&quot;: &quot;test1&quot;,
              &quot;body&quot;: &quot;name=sample creative&amp;object_story_spec=&#123;\&quot;link_data\&quot;: &#123;\&quot;image_hash\&quot;: \&quot;&#123;result=create_adimage:$.images.*.hash&#125;\&quot;, \&quot;link\&quot;: \&quot;https://www.test12345.com\&quot;, \&quot;message\&quot;: \&quot;this is a sample message\&quot;&#125;, \&quot;page_id\&quot;:\&quot;12345678\&quot;&#125;&amp;degrees_of_freedom_spec=&#123;\&quot;creative_features_spec\&quot;: &#123;\&quot;standard_enhancements\&quot;: &#123;\&quot;enroll_status\&quot;: \&quot;OPT_OUT\&quot;&#125;&#125;&#125;&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/ads&quot;,
              &quot;body&quot;: &quot;adset_id=6004163746239&amp;redownload=1&amp;status=PAUSED&amp;optimization_goal=REACH&amp;billing_event=IMPRESSIONS&amp;&amp;creative=&#123;\&quot;creative_id\&quot;:\&quot;&#123;result=create_creative:$.id&#125;\&quot;&#125;&amp;targeting=&#123;\&quot;countries\&quot;:[\&quot;US\&quot;]&#125;&amp;name=test1&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/ads&quot;,
              &quot;body&quot;: &quot;adset_id=6004163746239&amp;redownload=1&amp;status=PAUSED&amp;optimization_goal=REACH&amp;billing_event=IMPRESSIONS&amp;&amp;creative=&#123;\&quot;creative_id\&quot;:\&quot;&#123;result=create_creative:$.id&#125;\&quot;&#125;&amp;targeting=&#123;\&quot;countries\&quot;:[\&quot;US\&quot;]&#125;&amp;name=test2&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/ads&quot;,
              &quot;body&quot;: &quot;adset_id=6004163746239&amp;redownload=1&amp;status=PAUSED&amp;optimization_goal=REACH&amp;billing_event=IMPRESSIONS&amp;&amp;creative=&#123;\&quot;creative_id\&quot;:\&quot;&#123;result=create_creative:$.id&#125;\&quot;&#125;&amp;targeting=&#123;\&quot;countries\&quot;:[\&quot;US\&quot;]&#125;&amp;name=test3&quot;
             &#125;
            ]&#039; https://graph.facebook.com/
```

The response includes individual response codes for each request and the standard Graph API response. For details, see [Making Multiple API Requests](https://developers.facebook.com/docs/graph-api/making-multiple-requests).

The [batched request](https://developers.facebook.com/docs/reference/api/batch) process uses the [JSONPath expression format](http://code.google.com/p/jsonpath/) to reference the previous requests.

### Update ads

You can update ads with batch requests. To updates bids for three [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup):

```
curl -F &#039;access_token=____&#039;
  -F &#039;batch=[
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/6004251715639&quot;,
              &quot;body&quot;: &quot;redownload=1&amp;name=new name&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &lt;API_VERSION&gt;/v6004251716039&quot;,
              &quot;body&quot;: &quot;redownload=1&amp;name=new name&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;POST&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/6004251715839&quot;,
              &quot;body&quot;: &quot;redownload=1&amp;name=new name&quot;
             &#125;
            ]&#039; https://graph.facebook.com
```

If you include `redownload=1` in the relative URL, you get full ad details including the ad ID. This helps identify which ads you updated.

To update ad creative, specify the entire creative, or provide a new creative ID. This is because [Ad Creatives](https://developers.facebook.com/docs/reference/ads-api/adcreative) cannot be edited after they have been created except for name and run status.

### Read ads

If you have a large number of [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup), split the request over multiple requests within a [batched request](https://developers.facebook.com/docs/reference/api/batch):

```
curl -F &#039;access_token=____&#039;
  -F &#039;batch=[
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/?ids=6003356308839,6004164369439&amp;fields=&lt;comma separated list of fields&gt;&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/6003356307839/ads&amp;fields=&lt;comma separated list of fields&gt;&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/ads?adset_ids=[6003356307839, 6004164259439]&amp;fields=&lt;comma separated list of fields&gt;&quot;
             &#125;
            ]&#039; https://graph.facebook.com
```

`6003356308839` and `6004164369439` are [ad](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup) ids and `6003356307839` and `6004164259439` are [ad set](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-campaign) ids.

### Ad insights &#123;#adinsights&#125;

If you have a large number of [Ad Insights](https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights) split the request over multiple requests within a [batched request](https://developers.facebook.com/docs/reference/api/batch):

```
curl -F &#039;access_token=____&#039;
  -F &#039;batch=[
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_19643108/insights?filtering=[&#123;field:&#039;ad.id&#039;,operator:&#039;IN&#039;,value:[6003356308839,6004164369439]&#125;]&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/6003356308839/insights&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_187687683/insights?filtering=[&#123;field:&#039;adset.id&#039;,operator:&#039;IN&#039;,value:[6003356307839, 6004164259439]&#125;]&quot;
             &#125;
            ]&#039; https://graph.facebook.com
```

In this example `6003356308839` and `6004164369439` are [ad](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup) ids and `6003356307839` and `6004164259439` are [ad set](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-campaign) ids.

For [Ad accounts](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-account) with a large number of [ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/adgroup), do not use `act_&lt;account_ID&gt;/adgroupstats` because it causes the request to time out.

### Batch requests for reach estimate

You can request up to 50 [reach estimates](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/basic-targeting) in a single [batched request](https://developers.facebook.com/docs/reference/api/batch). The following example shows the reach estimate being requested for 2 different [targeting specs](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/advanced-targeting):

```
curl -F &#039;access_token=____&#039;
  -F &#039;batch=[
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_600335/reachestimate?targeting_spec=&#123;&#039;geo_locations&#039;: &#123;&#039;countries&#039;:[&#039;US&#039;]&#125;&#125;&quot;
             &#125;,
             &#123;
              &quot;method&quot;: &quot;GET&quot;,
              &quot;relative_url&quot;: &quot;&lt;API_VERSION&gt;/act_600335/reachestimate?targeting_spec=&#123;&#039;geo_locations&#039;: &#123;&#039;countries&#039;:[&#039;FR&#039;]&#125;&#125;&quot;
             &#125;
            ]&#039; https://graph.facebook.com
```

## Batch API &#123;#batchapioverview&#125;

Batch API enables you to batch requests and send them asynchronously. Group several Graph API calls into one HTTP request, and execute them asynchronously without having to block. You can also specify dependencies between related operations.

Facebook processes each independent operation in parallel processes and your dependent operations sequentially. Each API call can have a maximum of 1000 requests.

### Make a batch API call

To make a Batch API call:

```
curl \
-F &quot;access_token=___&quot; \
-F &quot;name=asyncbatchreqs&quot; \
-F &quot;adbatch=&lt;an array of requests&gt;&quot;\
&quot;https://graph.facebook.com/v25.0/act_&lt;AD_ACCOUNT_ID&gt;/async_batch_requests&quot;
```

Provide an array of `HTTP POST` requests as `JSON` arrays. Each request has:

* `name`
* `relative_url` - portion of URL after graph.facebook.com
* `body`

The API returns an id you use to query the progress of requests.

For example, create a campaign with an ad set with JSONPath Format to reference the previous requests:

```
curl \
-F &quot;access_token=___&quot; \
-F &quot;name=batchapiexample&quot; \
-F &quot;adbatch=[
  &#123;
    &#039;name&#039;: &#039;create-campaign&#039;,
    &#039;relative_url&#039;: &#039;act_123456/campaigns&#039;,
    &#039;body&#039;: &#039;name%3DTest+Campaign%26objective%3DLINK_CLICKS%26status%3DPAUSED%26buying_type%3DAUCTION&#039;,
  &#125;,
  &#123;
    &#039;name&#039;: &#039;create-adset&#039;,
    &#039;relative_url&#039;: &#039;act_123456/adsets&#039;,
    &#039;body&#039;: &#039;targeting%3D%7B%22geo_locations%22%3A%7B%22countries%22%3A%5B%22US%22%5D%7D%7D%26daily_budget%3D5000%26campaign_id%3D%7Bresult%3Dcreate-campaign%3A%24.id%7D%26bid_amount%3D2%26name%3DFirst%2BAd%2BSet%20Test%26billing_event%3DLINK_CLICKS&#039;,
  &#125;,
]&quot; \
https://graph.facebook.com/&lt;API_VERSION&gt;/act_123456/async_batch_requests
```

To get a request set status:

```
curl –G \
-d &quot;access_token=___&quot; \
-d &quot;fields=&lt;comma separated list of fields&gt;&quot; \
&quot;https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;&quot;
```

This returns overall status for async request sets as JSON objects. Not all fields are returned by default. To include them, specify the `fields`, such as `fields=id,owner_id,name,total_count,success_count,error_count,is_completed`

| Name | Description |
| --- | --- |
| `id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;`id` of current async request set. |
| `owner_id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;Object that owns this async request set. If you create ads, `owner_id` is the ad account id. |
| `name`&lt;br&gt;&lt;br&gt;type: string | **Shown by default.**&lt;br&gt;&lt;br&gt;Name of this async request set |
| `is_completed`&lt;br&gt;&lt;br&gt;type: boolean | **Shown by default.**&lt;br&gt;&lt;br&gt;All async requests in set complete |
| `total_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Total requests count for this request set |
| `initial_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests not served yet |
| `in_progress_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests in progress |
| `success_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests finished and successful |
| `error_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests finished and failed |
| `canceled_count`&lt;br&gt;&lt;br&gt;type: int | **Not shown by default.**&lt;br&gt;&lt;br&gt;Number of requests canceled by user |
| `notification_uri`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Notification URI for this async request set. |
| `notification_mode`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Ways to receive notification. Valid values:&lt;br&gt;&lt;br&gt;- `OFF` – No notifications&lt;br&gt;- `ON_COMPLETE` – Sends a notification when the whole set is complete. |
| `notification_result`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Result of sending notification. |
| `notification_status`&lt;br&gt;&lt;br&gt;type: string | **Not shown by default.**&lt;br&gt;&lt;br&gt;Notification status: `not_sent`, `sending`, or `sent` |

After you get overall status, you can get details for each request:

```
curl –G \
-d &quot;access_token=___&quot; \
-d &quot;fields=&lt;comma separated list of fields&gt;&quot; \
&quot;https://graph.facebook.com/v25.0/&lt;REQUEST_SET_ID&gt;/requests&quot;
```

This returns details as a JSON array. To include non-default fields, specify it in `fields`, such as `fields=id,scope_object_id,status,result,input,async_request_set`.

| Name | Description |
| --- | --- |
| `id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;ID of  individual async request |
| `scope_object_id`&lt;br&gt;&lt;br&gt;type: int | **Shown by default.**&lt;br&gt;&lt;br&gt;Parent ID of the object this request creates. If you create ads, this is ad set ID for the new ad. |
| `status`&lt;br&gt;&lt;br&gt;type: string | **Shown by default.**&lt;br&gt;&lt;br&gt;Status of this async request:&lt;br&gt;&lt;br&gt;- `Initial` – Not processed yet&lt;br&gt;- `In_progress` – Request is processing&lt;br&gt;- `Success` – Request finished and successful&lt;br&gt;- `Error` – Request finished and failed&lt;br&gt;- `Canceled` – Request canceled by user |
| `result`&lt;br&gt;&lt;br&gt;type: array | **Not shown by default.**&lt;br&gt;&lt;br&gt;If request finishes, show result.&lt;br&gt;For success, the result is same as&lt;br&gt;non-async API. For example, if you create an ad&lt;br&gt;creation, result is new ad ID.&lt;br&gt;For errors:&lt;br&gt;&lt;br&gt;- `error_code` – Error code returned&lt;br&gt;- `error_message` – Error message |
| `input`&lt;br&gt;&lt;br&gt;type: object | **Not shown by default.**&lt;br&gt;&lt;br&gt;Original input for this request. If you create an ad, the input is `adgroup_spec`. |
| `async_request_set`&lt;br&gt;&lt;br&gt;type: object | **Not shown by default.**&lt;br&gt;&lt;br&gt;Async request set containing this request. |

### List batch API requests for ad account

You can create multiple Batch API request sets. To query all request sets under an
ad account:

```
curl –G \
-d &quot;access_token=___&quot; \
&quot;https://graph.facebook.com/v25.0/act_&lt;AD_ACCOUNT_ID&gt;/async_requests&quot;
```

## ETags &#123;#etags&#125;

Marketing API supports [Etags](http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.19). This helps you tell if the data you query has changed since you last checked. How this works:

1. When you make a call, the response header includes an ETag with a value that is the hash of the data returned in the API call. Save this ETag value for use in the next step.
2. Next time you make the same API call, include the __If-None-Match__ request header with the ETag value you saved.
3. If the data has not changed, the response status code is `304 – Not Modified` and no data is returned.
4. If the data has changed since the last query, the data is returned as usual with a new ETag. Save the new ETag value and use it for subsequent calls.

While ETags help reduce data traffic, `If-None-Match GET` still counts against rate limits for your app.

The ETag is calculated using the entire response from the API call including its formatting. The formatting of the response may be impacted by the user agent string. Therefore, you should keep your user agent consistent between calls made from the same client.

### ETags examples &#123;#etag&#125;

To check if the user&#039;s adaccounts have changed.

__Step 1__: Determine the ETag for the current data

```
curl -i &quot;https://graph.beta.facebook.com/me/adaccounts?access_token=___&quot;
```

The response will be as follows:

```
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
Cache-Control: private, no-cache, no-store, must-revalidate
Content-Type: text/javascript; charset=UTF-8
ETag: &quot;7776cdb01f44354af8bfa4db0c56eebcb1378975&quot;
Expires: Sat, 01 Jan 2000 00:00:00 GMT
Pragma: no-cache
X-FB-Rev: 495685
X-FB-Server: 10.30.149.204
X-FB-Debug: CWbHcogdwUE8saMv6ML+8FacXFrE8ufhjjwxU2dQWaA=
X-Cnection: close
Date: Mon, 16 Jan 2012 12:07:44 GMT
Content-Length: 3273

&#123;&quot;data&quot;:[&#123;&quot;id&quot;:&quot;act.......
```

In this example the ETag is `&quot;7776cdb01f44354af8bfa4db0c56eebcb1378975&quot;`, note that the ETag includes the quotes (`&quot;`).

__Step 2__: Determine if there have been any changes to the data

```
curl -i -H &quot;If-None-Match: \&quot;7776cdb01f44354af8bfa4db0c56eebcb1378975\&quot;&quot; &quot;https://graph.beta.facebook.com/me/adaccounts?access_token=___&quot;
```

If nothing has changed the response will be as follows:

```
HTTP/1.1 304 Not Modified
Access-Control-Allow-Origin: *
Cache-Control: private, no-cache, no-store, must-revalidate
Content-Type: text/javascript; charset=UTF-8
Expires: Sat, 01 Jan 2000 00:00:00 GMT
Pragma: no-cache
X-FB-Rev: 495685
X-FB-Server: 10.30.177.190
X-FB-Debug: ImBhat3k07Nez5FvuS2lPWU0U2xxmxD4B3k9ua4Sk7Q=
X-Cnection: close
Date: Mon, 16 Jan 2012 12:09:17 GMT
Content-Length: 0
```

Note the `304 Not Modified` response. If the data had changed a normal API response would be returned.

A batch example to check if the user&#039;s ads have changed.

__Step 1__: Determine the ETag for the current data

```
curl -i &quot;curl -F &#039;access_token=___&#039; -F &#039;batch=[
  &#123;&quot;method&quot;:&quot;GET&quot;, &quot;relative_url&quot;: &quot;?ids=6003356308839,6004164369439&quot; &#125;,
  &#123;&quot;method&quot;:&quot;GET&quot;, &quot;relative_url&quot;: &quot;act_12345678/ads?campaign_ids=[6003356307839, 6004164259439]&quot;&#125;]&#039;
 https://graph.facebook.com&quot;
```

The response will contain ETag values as follows:

```
...&#123;&quot;name&quot;:&quot;ETag&quot;,&quot;value&quot;:&quot;\&quot;21d371640127490b2ed0387e8af3f0f8c9eff012\&quot;&quot;&#125;...
...&#123;&quot;name&quot;:&quot;ETag&quot;,&quot;value&quot;:&quot;\&quot;410e53bb257f116e8716e4ebcc76df1c567b87f4\&quot;&quot;&#125;...
```

In this example the ETags are `&quot;21d371640127490b2ed0387e8af3f0f8c9eff012&quot;` and `&quot;410e53bb257f116e8716e4ebcc76df1c567b87f4&quot;` note that the ETag includes the quotes (`&quot;`).

__Step 2__: Determine if there have been any changes to the data:

```
curl -F &#039;access_token=___&#039; -F &#039;batch=[
  &#123;&quot;method&quot;:&quot;GET&quot;, &quot;headers&quot;:[&quot;If-None-Match: \&quot;21d371640127490b2ed0387e8af3f0f8c9eff012\&quot;&quot;], &quot;relative_url&quot;: &quot;?ids=6003356308839,6004164369439&quot; &#125;,
  &#123;&quot;method&quot;:&quot;GET&quot;,  &quot;headers&quot;:[&quot;If-None-Match: \&quot;410e53bb257f116e8716e4ebcc76df1c567b87f4\&quot;&quot;], &quot;relative_url&quot;: &quot;act_12345678/ads?campaign_ids=[6003356307839, 6004164259439]&quot;&#125;]&#039;
https://graph.facebook.com
```

If nothing has changed the response is:

```
[&#123;
    &quot;code&quot;: 304,
    .
    .
    .
    &quot;body&quot;: null
&#125;,
&#123;
    &quot;code&quot;: 304,
    .
    .
    .
    &quot;body&quot;: null
&#125;]
```

Note the `304 Not Modified` response. If the data changed, Marketing API returns a normal API response.
