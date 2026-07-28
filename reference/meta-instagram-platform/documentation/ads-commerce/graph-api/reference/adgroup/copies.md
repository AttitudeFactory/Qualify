# Ad Copies



**Note:** The Marketing API has it is own rate limiting logic. If you are encountering errors mentioning a reached limit, see [Rate Limiting](https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting).

## Reading

The copies of this ad.

#### Example

### HTTP
```
GET /v25.0/&#123;ad-id&#125;/copies HTTP/1.1
Host: graph.facebook.com
```

### PHP SDK
```
/* PHP SDK v5.0.0 */
/* make the API call */
try &#123;
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb-&gt;get(
    &#039;/&#123;ad-id&#125;/copies&#039;,
    &#039;&#123;access-token&#125;&#039;
  );
&#125; catch(Facebook\Exceptions\FacebookResponseException $e) &#123;
  echo &#039;Graph returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125; catch(Facebook\Exceptions\FacebookSDKException $e) &#123;
  echo &#039;Facebook SDK returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125;
$graphNode = $response-&gt;getGraphNode();
/* handle the result */
```

### JavaScript SDK
```
/* make the API call */
FB.api(
    &quot;/&#123;ad-id&#125;/copies&quot;,
    function (response) &#123;
      if (response &amp;&amp; !response.error) &#123;
        /* handle the result */
      &#125;
    &#125;
);
```

### Android SDK
```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    &quot;/&#123;ad-id&#125;/copies&quot;,
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() &#123;
        public void onCompleted(GraphResponse response) &#123;
            /* handle the result */
        &#125;
    &#125;
).executeAsync();
```

### iOS SDK
```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:&#064;&quot;/&#123;ad-id&#125;/copies&quot;
                                      parameters:params
                                      HTTPMethod:&#064;&quot;GET&quot;];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) &#123;
    // Handle the result
&#125;];
```

Try it in [Graph API Explorer](https://developers.facebook.com/tools/explorer/?method=GET&amp;path=%7Bad-id%7D%2Fcopies&amp;version=v25.0)

If you want to learn how to use the Graph API, read our [Using Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api)

#### Parameters

| Parameter | Description |
| --- | --- |
| `date_preset`&lt;br&gt;&lt;br&gt;*enum&#123;today, yesterday, this_month, last_month, this_quarter, maximum, data_maximum, last_3d, last_7d, last_14d, last_28d, last_30d, last_90d, last_week_mon_sun, last_week_sun_sat, last_quarter, last_year, this_week_mon_today, this_week_sun_today, this_year&#125;* | Preset date range used to aggregate insights metrics&lt;br&gt; |
| `effective_status`&lt;br&gt;&lt;br&gt;*list&lt;string&gt;* | Filter Ads by effective status&lt;br&gt; |
| `time_range`&lt;br&gt;&lt;br&gt;*&#123;&#039;since&#039;:YYYY-MM-DD,&#039;until&#039;:YYYY-MM-DD&#125;* | Time range used to aggregate insights metrics&lt;br&gt;&lt;br&gt;&lt;br&gt;`since` *datetime*&lt;br&gt;A date in the format of &quot;YYYY-MM-DD&quot;, which means from the beginning midnight of that day.&lt;br&gt;&lt;br&gt;&lt;br&gt;`until` *datetime*&lt;br&gt;A date in the format of &quot;YYYY-MM-DD&quot;, which means to the beginning midnight of the following day.&lt;br&gt; |
| `updated_since`&lt;br&gt;&lt;br&gt;*integer* | Filter ads by updated since time&lt;br&gt; |

#### Fields

Reading from this edge will return a JSON formatted result:

```
&#123;
&quot;data&quot;: [],
&quot;paging&quot;: &#123;&#125;,
&quot;summary&quot;: &#123;&#125;
&#125;
```

##### data

A list of [Ad](https://developers.facebook.com/docs/graph-api/reference/adgroup) nodes.

##### paging

For more details about pagination, see the [Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api#paging).

##### summary

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like summary=__type__).

| Field | Description |
| --- | --- |
| `insights`&lt;br&gt;&lt;br&gt;*Edge&lt;AdsInsights&gt;* | Analytics summary for all objects&lt;br&gt; |
| `total_count`&lt;br&gt;&lt;br&gt;*unsigned int32* | Total number of objects&lt;br&gt;&lt;br&gt;&lt;br&gt;**[default]**&lt;br&gt; |

#### Error Codes

| Error Code | Description |
| --- | --- |
| 104 | Incorrect signature |

## Creating

### Targeting DSA Regulated Locations (European Union)

To copy an ad set targeted in the European Union&#039;s Digital Services Act (DSA) regulated locations, please set the payor/beneficiary information first. Otherwise the copying request may respond with one of the following errors:

**Payor missing error**

```
&#123;
  &quot;error&quot;: &#123;
    &quot;message&quot;: &quot;Invalid parameter&quot;,
    &quot;type&quot;: &quot;FacebookApiException&quot;,
    &quot;code&quot;: 100,
    &quot;error_data&quot;: &quot;&#123;\&quot;blame_field_specs\&quot;:[[\&quot;dsa_payor\&quot;]]&#125;&quot;,
    &quot;error_subcode&quot;: 3858079,
    &quot;is_transient&quot;: false,
    &quot;error_user_title&quot;: &quot;No payor provided in DSA regulated region&quot;,
    &quot;error_user_msg&quot;: &quot;The DSA requires ads to provide payor information in regulated regions. Updating/creating ad needs to provide payor of the ad.&quot;,
    &quot;fbtrace_id&quot;: &quot;fbtrace_id&quot;
  &#125;,
  &quot;__fb_trace_id__&quot;: &quot;fbtrace_id&quot;,
  &quot;__www_request_id__&quot;: &quot;request_id&quot;
&#125;
```

**Beneficiary missing error**

```
&#123;
  &quot;error&quot;: &#123;
    &quot;message&quot;: &quot;Invalid parameter&quot;,
    &quot;type&quot;: &quot;FacebookApiException&quot;,
    &quot;code&quot;: 100,
    &quot;error_data&quot;: &quot;&#123;\&quot;blame_field_specs\&quot;:[[\&quot;dsa_beneficiary\&quot;]]&#125;&quot;,
    &quot;error_subcode&quot;: 3858081,
    &quot;is_transient&quot;: false,
    &quot;error_user_title&quot;: &quot;No payor/beneficiary provided in DSA regulated location&quot;,
    &quot;error_user_msg&quot;: &quot;The DSA requires ads to provide beneficiary information in regulated regions. Updating/creating ad needs to provide beneficiary of the ad.&quot;,
    &quot;fbtrace_id&quot;: &quot;fbtrace_id&quot;
  &#125;,
  &quot;__fb_trace_id__&quot;: &quot;fbtrace_id&quot;,
  &quot;__www_request_id__&quot;: &quot;request_id&quot;
&#125;
```

### Creative Parameters

When making a copy of an ad, you may overwrite fields on the creative spec by using the `creative_parameters` argument. Currently, this supports overwriting the API spec at the top-level parameter level, i.e. when `creative_parameter` supplied, the new creative will use all of the newly provided value for any valid parameter.  Otherwise, the values from the source ad’s creative will be used.

Find out more about the available fields in our [documentation for ad creatives](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-account/adcreatives).

#### Creative spec overwrite example

Original creative

```
&#123;
  &quot;body&quot;: &quot;original ad body&quot;,
  &quot;degrees_of_freedom_spec&quot;: &#123;
    &quot;creative_features_spec&quot;: &#123;
      &quot;text_optimizations&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;,
      &quot;inline_comment&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;
    &#125;
  &#125;,
  &quot;image_url&quot;: &quot;https://example.com/my-image-url&quot;,
  &quot;name&quot;: &quot;original ad name&quot;,
  &quot;title&quot;: &quot;original ad body&quot;
&#125;
```

Supplied input for copy operation

```
&#123;
  &quot;degrees_of_freedom_spec&quot;: &#123;
    &quot;creative_features_spec&quot;: &#123;
      &quot;text_optimizations&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;,
      &quot;image_touchups&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;
    &#125;
  &#125;,
  &quot;image_url&quot;: &quot;https://example.com/my–other-image-url&quot;,
  &quot;url_tags&quot;: &quot;source=fb_ad&quot;
&#125;
```

Resulting creative

```
&#123;
  &quot;body&quot;: &quot;original ad body&quot;,
  &quot;degrees_of_freedom_spec&quot;: &#123;
    &quot;creative_features_spec&quot;: &#123;
      &quot;text_optimizations&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;,
      &quot;image_touchups&quot;: &#123;
        &quot;enroll_status&quot;: &quot;OPT_IN&quot;
      &#125;
    &#125;
  &#125;,
  &quot;image_url&quot;: &quot;https://example.com/my–other-image-url&quot;,
  &quot;name&quot;: &quot;original ad name&quot;,
  &quot;title&quot;: &quot;original ad body&quot;,
  &quot;url_tags&quot;: &quot;source=fb_ad&quot;
&#125;
```

Note the following:

- `body`, `name`, `title` are not supplied in the input spec, so they are carried over from the original

- `url_tags` is defined in the input spec, but not in the original spec.  It is defined in the new spec

- `image_url `is defined in both.  The input value is used in the new spec.

- `degrees_of_freedom_spec` defines opt-ins for `text_optimizations` and `inline_comment` in the original spec, and only `text_optimizations` and `image_touchups` in the new spec.  The input `degrees_of_freedom_spec` completely overrides the old one, and previously defined sub-fields are not used.

### /&#123;ad_id&#125;/copies
You can make a POST request to *copies* edge from the following paths:

- [/&#123;ad_id&#125;/copies](https://developers.facebook.com/documentation/ads-commerce/graph-api/reference/adgroup/copies)

When posting to this edge, an [Ad](https://developers.facebook.com/docs/graph-api/reference/adgroup) will be created.

#### Parameters

| Parameter | Description |
| --- | --- |
| `adset_id`&lt;br&gt;&lt;br&gt;*numeric string or integer* | Single ID of an adset object to make the parent of the copy. Ignore if you want to keep the copy under the original adset parent.&lt;br&gt; |
| `creative_parameters`&lt;br&gt;&lt;br&gt;*AdCreative* | Creative inputs which will be used to construct the creative in the new ad.  Overwrites happen at the top level.  If no input is provided, the new ad will be created with an identical ad creative.  If some input is provided, those parameters will be assigned to the ad creative created by this API call.&lt;br&gt;&lt;br&gt;&lt;br&gt;Accepts all ad creative parameters as specified in /documentation/ads-commerce/marketing-api/reference/ad-account/adcreatives&lt;br&gt;&lt;br&gt;**[supports emoji]**&lt;br&gt; |
| `rename_options`&lt;br&gt;&lt;br&gt;*JSON or object-like arrays* | Rename options&lt;br&gt;&lt;br&gt;&lt;br&gt;`rename_strategy` *enum &#123;DEEP_RENAME, ONLY_TOP_LEVEL_RENAME, NO_RENAME&#125;*&lt;br&gt;&lt;br&gt;**Default value: **`ONLY_TOP_LEVEL_RENAME`&lt;br&gt;`DEEP_RENAME`: will change this object&#039;s name and children&#039;s names in the copied object. `ONLY_TOP_LEVEL_RENAME`: will change the this object&#039;s name but won&#039;t change the children&#039;s name in the copied object. `NO_RENAME`: will change no name in the copied object&lt;br&gt;&lt;br&gt;&lt;br&gt;`rename_prefix` *string*&lt;br&gt;A prefix to copy names. Defaults to null if not provided.&lt;br&gt;&lt;br&gt;&lt;br&gt;`rename_suffix` *string*&lt;br&gt;A suffix to copy names. Defaults to null if not provided and appends a localized string of `- Copy` based on the ad account locale.&lt;br&gt; |
| `status_option`&lt;br&gt;&lt;br&gt;*enum &#123;ACTIVE, PAUSED, INHERITED_FROM_SOURCE&#125;* | **Default value: **`PAUSED`&lt;br&gt;`ACTIVE`: the copied ad will have active status. `PAUSED`: the copied ad will have paused status. `INHERITED_FROM_SOURCE`: the copied ad will have the parent status.&lt;br&gt; |

#### Return Type

This endpoint supports [read-after-write](https://developers.facebook.com/docs/graph-api/overview#read-after-write) and will read the node represented by *copied_ad_id* in the return type.

```
Struct  &#123;
copied_ad_id: numeric string,
&#125;
```

#### Error Codes

| Error Code | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |

## Updating

You can&#039;t perform this operation on this endpoint.

## Deleting

You can&#039;t perform this operation on this endpoint.

