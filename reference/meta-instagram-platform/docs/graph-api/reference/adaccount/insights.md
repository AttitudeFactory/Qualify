Graph API Version

[v25.0](#)

# Ad Account, Insights

The Insights API can return several metrics which are *estimated* or *in-development*. In some cases a metric may be **both** *estimated and in-development*.

* **Estimated** - Provide directional insights for outcomes that are hard to precisely quantify. They may evolve as we gather more data. See [Ads Help Center, Estimated metrics](https://www.facebook.com/business/help/181058782494426?helpref=faq_content#estimated).
* **In Development** - Still being tested and may change as we improve our methodologies. We encourage you to use it for directional guidance, but please use caution when using it for historical comparisons or strategic planning. See [Ads Help Center, In development metrics](https://www.facebook.com/business/help/181058782494426?helpref=faq_content#indevelopment).

For more information, see [Insights API, Estimated and Deprecated Metrics](/docs/marketing-api/insights/estimated-in-development)

Facebook will no longer be able to aggregate non-inline conversion metric values across iOS 14.5 and non-iOS 14.5 campaigns due to differences in attribution logic. Querying across iOS 14.5 and non-iOS 14.5 campaigns will result in no data getting returned for non-inline conversion metrics such as app installs and purchases. Inline event metrics like impressions, link clicks, and video views, however, can still be aggregated. Please visit our [changelog](https://developers.facebook.com/docs/graph-api/changelog/non-versioned-changes/jan-19-2021) for more information.

The `date_preset = lifetime` parameter is disabled in Graph API v10.0 and replaced with `date_preset = maximum`, which returns a maximum of 37 months of data. For v9.0 and below, `date_preset = maximum` will be enabled on May 25, 2021, and any `lifetime` calls will default to `maximum` and return only 37 months of data.

## Reading

Provides insights on your advertising performance. Allows for deduped metrics across child objects, such as `unique_clicks`, sorting of metrics, and async reporting.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=GET&path=%3CAD_SET_ID%3E%2Finsights%3Ffields%3Dimpressions%26breakdown%3Dpublisher_platform&version=v25.0)

```
GET /v25.0/<AD_SET_ID>/insights?fields=impressions&breakdown=publisher_platform HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/<AD_SET_ID>/insights?fields=impressions&breakdown=publisher_platform',
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
    "/<AD_SET_ID>/insights",
    {
        "fields": "impressions",
        "breakdown": "publisher_platform"
    },
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
Bundle params = new Bundle();
params.putString("fields", "impressions");
params.putString("breakdown", "publisher_platform");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/<AD_SET_ID>/insights",
    params,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"fields": @"impressions",
  @"breakdown": @"publisher_platform",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/<AD_SET_ID>/insights"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

```
curl -X GET -G \
  -d 'fields="impressions"' \
  -d 'breakdown="publisher_platform"' \
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/<AD_SET_ID>/insights
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `action_attribution_windows`  list<enum{1d\_view, 7d\_view, 28d\_view, 1d\_click, 7d\_click, 28d\_click, 1d\_ev, dda, default, 7d\_view\_first\_conversion, 28d\_view\_first\_conversion, 7d\_view\_all\_conversions, 28d\_view\_all\_conversions, skan\_view, skan\_click, skan\_click\_second\_postback, skan\_view\_second\_postback, skan\_click\_third\_postback, skan\_view\_third\_postback, incrementality, incrementality\_first\_conversion, incrementality\_all\_conversions, custom, 1d\_sequenced, 7d\_sequenced, 28d\_sequenced}> | Default value: `default`  The attribution window for the actions.   The attribution window determines the window (e.g. 7d) and engagement type (e.g click) that’s used as a filter to report actions. See [About attribution settings and models](https://www.facebook.com/business/help/460276478298895?id=561906377587030) for examples.  The `default` option means `["7d_click","1d_view"]`. |
| `action_breakdowns`  list<enum{action\_device, conversion\_destination, matched\_persona\_id, matched\_persona\_name, signal\_source\_bucket, standard\_event\_content\_type, action\_canvas\_component\_name, action\_carousel\_card\_id, action\_carousel\_card\_name, action\_destination, action\_reaction, action\_target\_id, action\_type, action\_video\_sound, action\_video\_type, is\_business\_ai\_assisted}> | Default value: `Vec`  How to break down action results. Supports more than one breakdowns. Default value is ["action\_type"].  Note: you must also include `actions` field whenever `action_breakdowns` is specified. |
| `action_report_time`  enum{impression, conversion, mixed, lifetime} | Determines the report time of action stats. For example, if a person saw the ad on Jan 1st but converted on Jan 2nd, when you query the API with `action_report_time=impression`, you see a conversion on Jan 1st. When you query the API with `action_report_time=conversion`, you see a conversion on Jan 2nd. |
| `breakdowns`  list<enum{ad\_extension\_domain, ad\_extension\_url, ad\_format\_asset, age, app\_id, body\_asset, breakdown\_ad\_objective, breakdown\_reporting\_ad\_id, call\_to\_action\_asset, coarse\_conversion\_value, comscore\_market, country, creative\_automation\_asset\_id, creative\_relaxation\_asset\_type, crm\_advertiser\_l12\_territory\_ids, crm\_advertiser\_subvertical\_id, crm\_advertiser\_vertical\_id, crm\_ult\_advertiser\_id, description\_asset, existing\_post\_id, fidelity\_type, flexible\_format\_asset\_type, gen\_ai\_asset\_type, gender, hsid, image\_asset, impression\_device, instagram\_ads\_follow\_type, instagram\_ads\_instagram\_media\_product\_type, instagram\_ads\_time\_since\_creation\_bucket, internal\_campaign\_id, is\_auto\_advance, is\_conversion\_id\_modeled, is\_rendered\_as\_delayed\_skip\_ad, landing\_destination, link\_url\_asset, mdsa\_landing\_destination, media\_asset\_url, media\_creator, media\_destination\_url, media\_format, media\_origin\_url, media\_text\_content, media\_type, pa\_creator\_ig\_handle, postback\_sequence\_index, product\_brand\_breakdown, product\_category\_breakdown, product\_custom\_label\_0\_breakdown, product\_custom\_label\_1\_breakdown, product\_custom\_label\_2\_breakdown, product\_custom\_label\_3\_breakdown, product\_custom\_label\_4\_breakdown, product\_group\_content\_id\_breakdown, product\_id, redownload, region, rta\_ugc\_topic, skan\_campaign\_id, skan\_conversion\_id, skan\_version, sot\_attribution\_model\_type, sot\_attribution\_window, sot\_channel, sot\_event\_type, sot\_source, title\_asset, user\_persona\_id, user\_persona\_name, video\_asset, zip, rule\_set\_id, rule\_set\_name, dma, frequency\_value, overlap\_segment, hourly\_stats\_aggregated\_by\_advertiser\_time\_zone, hourly\_stats\_aggregated\_by\_audience\_time\_zone, mmm, place\_page\_id, publisher\_platform, platform\_position, device\_platform, standard\_event\_content\_type, conversion\_destination, signal\_source\_bucket, reels\_trending\_topic, marketing\_messages\_btn\_name, impression\_view\_time\_advertiser\_hour\_v2}> | How to break down the result. For more than one breakdown, only certain combinations are available: See [Combining Breakdowns](/docs/marketing-api/insights/breakdowns#combiningbreakdowns) and the [Breakdowns](/docs/marketing-api/insights/breakdowns) page. The option `impression_device` cannot be used by itself. |
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | Default value: `last_30d`  Represents a relative time range. This field is ignored if `time_range` or `time_ranges` is specified. |
| `default_summary`  boolean | Default value: `false`  Determine whether to return a summary. If `summary` is set, this param is be ignored; otherwise, a summary section with the same fields as specified by `fields` will be included in the summary section. |
| `export_columns`  list<string> | Select fields on the exporting report file. It is an optional param. Exporting columns are equal to the param fields, if you leave this param blank |
| `export_format`  string | Set the format of exporting report file. If the export\_format is set, Report file is asyncrhonizely generated. It expects ["xls", "csv"]. |
| `export_name`  string | Set the file name of the exporting report. |
| `fields`  list<string> | Fields to be retrieved. Default behavior is to return impressions and spend. |
| `filtering`  list<Filter Object> | Default value: `Vec`  Filters on the report data. This parameter is an array of filter objects. |
| `field`  string | Required |
| `operator`  enum {EQUAL, NOT\_EQUAL, GREATER\_THAN, GREATER\_THAN\_OR\_EQUAL, LESS\_THAN, LESS\_THAN\_OR\_EQUAL, IN\_RANGE, NOT\_IN\_RANGE, CONTAIN, NOT\_CONTAIN, CONTAINS\_ANY, CONTAINS\_ALL, NOT\_CONTAINS\_ANY, STEM\_MATCH, IN, NOT\_IN, STARTS\_WITH, ENDS\_WITH, ANY, ALL, AFTER, BEFORE, ON\_OR\_AFTER, ON\_OR\_BEFORE, NONE, TOP} | Required |
| `value`  string | Required |
| `level`  enum {ad, adset, campaign, account} | Represents the level of result. |
| `limit`  integer | limit |
| `product_id_limit`  integer | Maximum number of product ids to be returned for each ad when breakdown by `product_id`. |
| `sort`  list<string> | Default value: `Vec`  Field to sort the result, and direction of sorting. You can specify sorting direction by appending "\_ascending" or "\_descending" to the sort field. For example, "reach\_descending". For actions, you can sort by action type in form of "actions:<action\_type>". For example, ["actions:link\_click\_ascending"]. This array supports no more than one element. By default, the sorting direction is ascending. |
| `summary`  list<string> | If this param is used, a summary section will be included, with the fields listed in this param. |
| `summary_action_breakdowns`  list<enum{action\_device, conversion\_destination, matched\_persona\_id, matched\_persona\_name, signal\_source\_bucket, standard\_event\_content\_type, action\_canvas\_component\_name, action\_carousel\_card\_id, action\_carousel\_card\_name, action\_destination, action\_reaction, action\_target\_id, action\_type, action\_video\_sound, action\_video\_type, is\_business\_ai\_assisted}> | Default value: `Vec`  Similar to `action_breakdowns`, but applies to summary. Default value is ["action\_type"]. |
| `time_increment`  enum{monthly, all\_days} or integer | Default value: `all_days`  If it is an integer, it is the number of days from 1 to 90. After you pick a reporting period by using `time_range` or `date_preset`, you may choose to have the results for the whole period, or have results for smaller time slices. If "all\_days" is used, it means one result set for the whole period. If "monthly" is used, you will get one result set for each calendar month in the given period. Or you can have one result set for each N-day period specified by this param. This param is ignored if `time_ranges` is specified. |
| `time_range`  {'since':YYYY-MM-DD,'until':YYYY-MM-DD} | A single time range object. UNIX timestamp not supported. This param is ignored if `time_ranges` is provided. |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |
| `time_ranges`  list<{'since':YYYY-MM-DD,'until':YYYY-MM-DD}> | Array of time range objects. Time ranges can overlap, for example to return cumulative insights. Each time range will have one result set. You cannot have more granular results with `time_increment` setting in this case.If `time_ranges` is specified, `date_preset`, `time_range` and `time_increment` are ignored. |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |
| `use_account_attribution_setting`  boolean | Default value: `false`  When this parameter is set to `true`, your ads results will be shown using the attribution settings defined for the ad account. |
| `use_unified_attribution_setting`  boolean | When this parameter is set to `true`, your ads results will be shown using unified attribution settings defined at ad set level and parameter `use_account_attribution_setting` will be ignored. |

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

A list of AdsInsights nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=account_currency`).

| Field | Description |
| --- | --- |
| `account_currency`  string | Currency that is used by your ad account. |
| `account_id`  numeric string | The ID number of your ad account, which groups your advertising activity. Your ad account includes your campaigns, ads and billing.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `account_name`  string | The name of your ad account, which groups your advertising activity. Your ad account includes your campaigns, ads and billing. |
| `action_values`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total value of all conversions attributed to your ads. |
| `actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total number of actions Accounts Center accounts took that are attributed to your ads. Actions may include engagement, clicks or conversions. |
| `activity_recency`  string | activity\_recency |
| `ad_click_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | ad\_click\_actions |
| `ad_format_asset`  string | ad\_format\_asset |
| `ad_id`  numeric string | The unique ID of the ad you're viewing in reporting.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `ad_impression_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | ad\_impression\_actions |
| `ad_name`  string | The name of the ad you're viewing in reporting. |
| `adset_id`  numeric string | The unique ID of the ad set you're viewing in reporting. An ad set is a group of ads that share the same budget, schedule, delivery optimization and targeting.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `adset_name`  string | The name of the ad set you're viewing in reporting. An ad set is a group of ads that share the same budget, schedule, delivery optimization and targeting. |
| `anchor_event_attribution_setting`  string | anchor\_event\_attribution\_setting |
| `anchor_events_performance_indicator`  string | anchor\_events\_performance\_indicator |
| `attribution_setting`  string | The default attribution window to be used when attribution result is calculated. Each ad set has its own attribution setting value. The attribution setting for campaign or account is calculated based on existing ad sets. |
| `auction_bid`  numeric string | auction\_bid |
| `auction_competitiveness`  numeric string | auction\_competitiveness |
| `auction_max_competitor_bid`  numeric string | auction\_max\_competitor\_bid |
| `body_asset`  AdAssetBody | body\_asset |
| `buying_type`  string | The method by which you pay for and target ads in your campaigns: through dynamic auction bidding, fixed-price bidding, or reach and frequency buying. This field is currently only visible at the campaign level. |
| `campaign_id`  numeric string | The unique ID number of the ad campaign you're viewing in reporting. Your campaign contains ad sets and ads.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `campaign_name`  string | The name of the ad campaign you're viewing in reporting. Your campaign contains ad sets and ads. |
| `canvas_avg_view_percent`  numeric string | The average percentage of the Instant Experience that Accounts Center accounts saw. An Instant Experience is a screen that opens after someone interacts with your ad on a mobile device. It may include a series of interactive or multimedia components, including video, images product catalog and more. |
| `canvas_avg_view_time`  numeric string | The average total time, in seconds, that Accounts Center accounts spent viewing an Instant Experience. An Instant Experience is a screen that opens after someone interacts with your ad on a mobile device. It may include a series of interactive or multimedia components, including video, images product catalog and more. |
| `catalog_segment_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of actions performed attributed to your ads promoting your catalog segment, broken down by action type. |
| `catalog_segment_value`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total value of all conversions from your catalog segment attributed to your ads. |
| `catalog_segment_value_mobile_purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from mobile app purchases for your catalog segment. |
| `catalog_segment_value_omni_purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from all purchases for your catalog segment. |
| `catalog_segment_value_website_purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from website purchases for your catalog segment. |
| `clicks`  numeric string | The number of clicks on your ads. |
| `coarse_conversion_value`  string | Allows advertisers and ad networks to receive directional post-install quality insights when the volume of campaign conversions isn't high enough to meet the privacy threshold needed to unlock the standard conversion value. Possible values of this breakdown are `low`, `medium` and `high`.   **Note:** This breakdown is only supported by the `total_postbacks_detailed_v4` field. |
| `comparison_node`  AdsInsightsComparison | Parent node that encapsulates fields to be compared (current time range Vs comparison time range) |
| `comscore_market`  string | comscore\_market |
| `configurable_attribution_action`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | configurable\_attribution\_action |
| `configurable_attribution_actionvalue`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | configurable\_attribution\_actionvalue |
| `configurable_audience_overlap_reach`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | configurable\_audience\_overlap\_reach |
| `configurable_reachbyfrequency_action`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | configurable\_reachbyfrequency\_action |
| `configurable_reachbyfrequency_converters_count`  numeric string | configurable\_reachbyfrequency\_converters\_count |
| `configurable_reachbyfrequency_impressions_cost`  numeric string | configurable\_reachbyfrequency\_impressions\_cost |
| `configurable_reachbyfrequency_impressions_count`  numeric string | configurable\_reachbyfrequency\_impressions\_count |
| `configurable_reachbyfrequency_reach`  numeric string | configurable\_reachbyfrequency\_reach |
| `conversion_values`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | conversion\_values |
| `conversions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | conversions |
| `converted_product_app_custom_event_fb_mobile_purchase`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_app\_custom\_event\_fb\_mobile\_purchase |
| `converted_product_app_custom_event_fb_mobile_purchase_value`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_app\_custom\_event\_fb\_mobile\_purchase\_value |
| `converted_product_offline_purchase`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_offline\_purchase |
| `converted_product_offline_purchase_value`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_offline\_purchase\_value |
| `converted_product_omni_purchase`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_omni\_purchase |
| `converted_product_omni_purchase_values`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_omni\_purchase\_values |
| `converted_product_quantity`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of products purchased which are recorded by your merchant partner's pixel or app SDK for a given product ID and driven by your ads. Has to be used together with converted product ID breakdown. |
| `converted_product_value`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The value of purchases recorded by your merchant partner's pixel or app SDK for a given product ID and driven by your ads. Has to be used together with converted product ID breakdown. |
| `converted_product_website_pixel_purchase`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_website\_pixel\_purchase |
| `converted_product_website_pixel_purchase_value`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | converted\_product\_website\_pixel\_purchase\_value |
| `cost_per_15_sec_video_view`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_15\_sec\_video\_view |
| `cost_per_2_sec_continuous_video_view`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_2\_sec\_continuous\_video\_view |
| `cost_per_6_sec_video_view`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_6\_sec\_video\_view |
| `cost_per_action_type`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average cost of a relevant action. |
| `cost_per_ad_click`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_ad\_click |
| `cost_per_conversion`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_conversion |
| `cost_per_dda_countby_convs`  numeric string | cost\_per\_dda\_countby\_convs |
| `cost_per_inline_link_click`  numeric string | The average cost of each inline link click. |
| `cost_per_inline_post_engagement`  numeric string | The average cost of each inline post engagement. |
| `cost_per_objective_result`  list<AdsInsightsResult> | The average cost per objective result from your ads. Objective results are what you're trying to get the most of in your ad campaign, based on the objective you selected. |
| `cost_per_one_thousand_ad_impression`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_one\_thousand\_ad\_impression |
| `cost_per_outbound_click`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average cost for each outbound click. |
| `cost_per_result`  list<AdsInsightsResult> | The average cost per result from your ads. |
| `cost_per_thruplay`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average cost for each ThruPlay. This metric is in development. |
| `cost_per_unique_action_type`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average cost of each unique action. This metric is estimated. |
| `cost_per_unique_click`  numeric string | The average cost for each unique click (all). This metric is estimated. |
| `cost_per_unique_conversion`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | cost\_per\_unique\_conversion |
| `cost_per_unique_inline_link_click`  numeric string | The average cost of each unique inline link click. This metric is estimated. |
| `cost_per_unique_outbound_click`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average cost for each unique outbound click. This metric is estimated. |
| `country`  string | country |
| `cpc`  numeric string | The average cost for each click (all). |
| `cpm`  numeric string | The average cost for 1,000 impressions. |
| `cpp`  numeric string | The average cost to reach 1,000 Accounts Center accounts. This metric is estimated. |
| `created_time`  string | created\_time |
| `creative_automation_asset_id`  AdAssetMedia | creative\_automation\_asset\_id |
| `creative_diversity_data`  list<CreativeDiversityData> | creative\_diversity\_data |
| `creative_diversity_label`  string | creative\_diversity\_label |
| `creative_diversity_score`  string | creative\_diversity\_score |
| `creative_fatigue_summary`  list<CreativeFatigueSummary> | creative\_fatigue\_summary |
| `creative_fatigued_ads`  list<CreativeFatiguedAds> | creative\_fatigued\_ads |
| `creative_relaxation_asset_type`  string | creative\_relaxation\_asset\_type |
| `ctr`  numeric string | The percentage of times Accounts Center accounts saw your ad and performed a click (all). |
| `date_start`  string | The start date for your data. This is controlled by the date range you've selected for your reporting view.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `date_stop`  string | The end date for your data. This is controlled by the date range you've selected for your reporting view.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `dda_countby_convs`  numeric string | dda\_countby\_convs |
| `dda_results`  list<AdsInsightsDdaResult> | dda\_results |
| `description_asset`  AdAssetDescription | description\_asset |
| `device_platform`  string | device\_platform |
| `dma`  string | dma |
| `fidelity_type`  string | To differentiate StoreKit-rendered ads from view-through ads, SKAdNetwork defines a fidelity-type parameter, which you include in the ad signature and receive in the install-validation postback. Use a fidelity-type value of `1` for StoreKit-rendered ads and attributable web ads, and `0` for view-through ads.   **Note:** This breakdown is only supported by the `total_postbacks_detailed_v4` field. |
| `flexible_format_asset_type`  string | flexible\_format\_asset\_type |
| `frequency`  numeric string | The average number of times each person saw your ad. This metric is estimated. |
| `frequency_value`  string | frequency\_value |
| `full_view_impressions`  numeric string | The number of Full Views on your Page's posts as a result of your ad. |
| `full_view_reach`  numeric string | The number of Accounts Center accounts that performed a Full View on your Page's post as a result of your ad. |
| `gen_ai_asset_type`  string | gen\_ai\_asset\_type |
| `hourly_stats_aggregated_by_advertiser_time_zone`  string | hourly\_stats\_aggregated\_by\_advertiser\_time\_zone |
| `hourly_stats_aggregated_by_audience_time_zone`  string | hourly\_stats\_aggregated\_by\_audience\_time\_zone |
| `hsid`  string | The `hsid` key is available for ad impressions that use SKAdNetwork 4 and later. This integer can have up to four digits. You can encode information about your advertisement in each set of digits; you may receive two, three, or all four digits of the sourceIdentifier in the first winning postback, depending on the ad impression's postback data tier.   **Note:** This breakdown is only supported by the `total_postbacks_detailed_v4` field. |
| `image_asset`  AdAssetImage | image\_asset |
| `impression_device`  string | impression\_device |
| `impressions`  numeric string | The number of times your ads were on screen.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `inline_link_click_ctr`  numeric string | The percentage of time Accounts Center accounts saw your ads and performed an inline link click. |
| `inline_link_clicks`  numeric string | The number of clicks on links to select destinations or experiences, on or off Facebook-owned properties. Inline link clicks use a fixed 1-day-click attribution window. |
| `inline_post_engagement`  numeric string | The total number of actions that Accounts Center accounts take involving your ads. Inline post engagements use a fixed 1-day-click attribution window. |
| `instagram_profile_follow`  numeric string | instagram profile follow |
| `instagram_upcoming_event_reminders_set`  numeric string | instagram\_upcoming\_event\_reminders\_set |
| `instant_experience_clicks_to_open`  numeric string | instant\_experience\_clicks\_to\_open |
| `instant_experience_clicks_to_start`  numeric string | instant\_experience\_clicks\_to\_start |
| `instant_experience_outbound_clicks`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | instant\_experience\_outbound\_clicks |
| `interactive_component_tap`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | interactive\_component\_tap |
| `is_auto_advance`  string | is\_auto\_advance |
| `landing_page_view_per_link_click`  numeric string | landing\_page\_view\_per\_link\_click |
| `marketing_messages_delivery_rate`  numeric string | The number of messages delivered divided by the number of messages sent. Some messages may not be delivered, such as when a customer's device is out of service. This metric doesn't include messages sent to Europe and Japan. |
| `media_asset`  AdAssetMedia | media\_asset |
| `mobile_app_purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from mobile app purchases. This is based on the value that you assigned when you set up the app event. |
| `msa_seller_id`  string | msa\_seller\_id |
| `multi_event_conversion_attribution_setting`  string | multi\_event\_conversion\_attribution\_setting |
| `objective`  string | The objective reflecting the goal you want to achieve with your advertising. It may be different from the selected objective of the campaign in some cases. |
| `objective_result_rate`  list<AdsInsightsResult> | The number of objective results you received divided by the number of impressions. |
| `objective_results`  list<AdsInsightsResult> | The number of responses you wanted to achieve from your ad campaign, based on your selected objective. For example, if you selected promote your Page as your campaign objective, this metric shows the number of Page likes that happened as a result of your ads. Also known as results. |
| `opportunity_score_l4`  numeric string | opportunity\_score\_l4 |
| `optimization_goal`  string | The optimization goal you selected for your ad or ad set. Your optimization goal reflects what you want to optimize for the ads. |
| `outbound_clicks`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of clicks on links that take Accounts Center accounts off Facebook-owned properties. |
| `outbound_clicks_ctr`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The percentage of times Accounts Center accounts saw your ad and performed an outbound click. |
| `overlap_segment`  string | overlap\_segment |
| `platform_position`  string | platform\_position |
| `postback_sequence_index`  string | Sequence of postbacks received from SkAdNetwork API version 4.0. Possible values of this breakdown are `0` (first postback), `1` (second postback) and `2` (third postback).   **Note:** This breakdown is only supported by the `total_postbacks_detailed_v4` field. |
| `product_brand_breakdown`  string | product\_brand\_breakdown |
| `product_category_breakdown`  string | product\_category\_breakdown |
| `product_custom_label_0_breakdown`  string | product\_custom\_label\_0\_breakdown |
| `product_custom_label_1_breakdown`  string | product\_custom\_label\_1\_breakdown |
| `product_custom_label_2_breakdown`  string | product\_custom\_label\_2\_breakdown |
| `product_custom_label_3_breakdown`  string | product\_custom\_label\_3\_breakdown |
| `product_custom_label_4_breakdown`  string | product\_custom\_label\_4\_breakdown |
| `product_group_content_id_breakdown`  string | product\_group\_content\_id\_breakdown |
| `product_group_retailer_id`  string | product\_group\_retailer\_id |
| `product_id`  string | product\_id |
| `product_retailer_id`  string | product\_retailer\_id |
| `product_set_id_breakdown`  string | product\_set\_id\_breakdown |
| `product_vendor_id_breakdown`  string | product\_vendor\_id\_breakdown |
| `product_views`  string | product\_views |
| `promoted_product_set_result`  string | promoted\_product\_set\_result |
| `publisher_platform`  string | publisher\_platform |
| `purchase_per_landing_page_view`  numeric string | purchase\_per\_landing\_page\_view |
| `purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from purchases. This is based on information received from one or more of your connected Facebook Business Tools and attributed to your ads. |
| `qualifying_question_qualify_answer_rate`  numeric string | qualifying\_question\_qualify\_answer\_rate |
| `reach`  numeric string | The number of Accounts Center accounts that saw your ads at least once. Reach is different from impressions, which may include multiple views of your ads by the same Accounts Center accounts. This metric is estimated. |
| `redownload`  string | Boolean flag that indicates the customer redownloaded and reinstalled the app when the value is true. A `1` indicates customer has reinstalled the app and `0` indicates that customer hasn’t reinstalled the app   **Note:** This breakdown is only supported by the `total_postbacks_detailed_v4` field. |
| `reels_trending_topic`  string | reels\_trending\_topic |
| `result_rate`  list<AdsInsightsResult> | The percentage of results you received out of all the views of your ads. |
| `result_values_performance_indicator`  string | result\_values\_performance\_indicator |
| `results`  list<AdsInsightsResult> | The number of times your ad achieved an outcome, based on the objective and settings you selected. |
| `rta_ugc_topic`  string | rta\_ugc\_topic |
| `rule_asset`  AdAssetRule | rule\_asset |
| `rule_set_id`  string | rule\_set\_id |
| `rule_set_name`  string | rule\_set\_name |
| `shop_clicks`  string | shop\_clicks |
| `shops_assisted_purchases`  string | shops\_assisted\_purchases |
| `skan_version`  string | skan\_version |
| `social_spend`  numeric string | The total amount you've spent so far for your ads showed with social information. (ex: Jane Doe likes this). |
| `spend`  numeric string | The estimated total amount of money you've spent on your campaign, ad set or ad during its schedule. This metric is estimated.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `title_asset`  AdAssetTitle | title\_asset |
| `total_card_view`  string | total\_card\_view |
| `updated_time`  string | updated\_time |
| `user_segment_key`  string | user\_segment\_key |
| `video_30_sec_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video played for at least 30 seconds, or for nearly its total length if it's shorter than 30 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. |
| `video_6_sec_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | video\_6\_sec\_watched\_actions |
| `video_asset`  AdAssetVideo | video\_asset |
| `video_avg_time_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The average time a video was played, including any time spent replaying the video for a single impression. |
| `video_continuous_2_sec_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | video\_continuous\_2\_sec\_watched\_actions |
| `video_p100_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video was played at 100% of its length, including plays that skipped to this point. |
| `video_p25_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video was played at 25% of its length, including plays that skipped to this point. |
| `video_p50_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video was played at 50% of its length, including plays that skipped to this point. |
| `video_p75_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video was played at 75% of its length, including plays that skipped to this point. |
| `video_p95_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video was played at 95% of its length, including plays that skipped to this point. |
| `video_play_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The number of times your video starts to play. This is counted for each impression of a video, and excludes replays. This metric is in development. |
| `video_play_curve_actions`  list<AdsHistogramStats> | A video-play based curve graph that illustrates the percentage of video plays that reached a given second. Entries 0 to 14 represent seconds 0 thru 14. Entries 15 to 17 represent second ranges [15 to 20), [20 to 25), and [25 to 30). Entries 18 to 20 represent second ranges [30 to 40), [40 to 50), and [50 to 60). Entry 21 represents plays over 60 seconds. |
| `video_play_retention_0_to_15s_actions`  list<AdsHistogramStats> | video\_play\_retention\_0\_to\_15s\_actions |
| `video_play_retention_20_to_60s_actions`  list<AdsHistogramStats> | video\_play\_retention\_20\_to\_60s\_actions |
| `video_play_retention_graph_actions`  list<AdsHistogramStats> | video\_play\_retention\_graph\_actions |
| `video_time_watched_actions`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | video\_time\_watched\_actions |
| `website_ctr`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The percentage of times Accounts Center accounts saw your ad and performed a link click. |
| `website_purchase_roas`  [list<AdsActionStats>](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/) | The total return on ad spend (ROAS) from website purchases. This is based on the value of all conversions recorded by the Facebook pixel on your website and attributed to your ads. |
| `wish_bid`  numeric string | wish\_bid |
| `zip`  string | zip |

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 3018 | The start date of the time range cannot be beyond 37 months from the current date |
| 613 | Calls to this api have exceeded the rate limit. |
| 2642 | Invalid cursors values |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 190 | Invalid OAuth 2.0 Access Token |
| 2500 | Error parsing graph query |
| 105 | The number of parameters exceeded the maximum for this operation |
| 3001 | Invalid query |

## Creating

You can make a POST request to `insights` edge from the following paths:

* [`/act_{ad_account_id}/insights`](/docs/marketing-api/reference/ad-account/insights/)

When posting to this edge, an [AdReportRun](/docs/marketing-api/reference/ad-report-run/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `action_attribution_windows`  list<enum{1d\_view, 7d\_view, 28d\_view, 1d\_click, 7d\_click, 28d\_click, 1d\_ev, dda, default, 7d\_view\_first\_conversion, 28d\_view\_first\_conversion, 7d\_view\_all\_conversions, 28d\_view\_all\_conversions, skan\_view, skan\_click, skan\_click\_second\_postback, skan\_view\_second\_postback, skan\_click\_third\_postback, skan\_view\_third\_postback, incrementality, incrementality\_first\_conversion, incrementality\_all\_conversions, custom, 1d\_sequenced, 7d\_sequenced, 28d\_sequenced}> | Default value: `default`  The attribution window for the actions. The attribution window determines the window (e.g. 7d) and engagement type (e.g click) that’s used as a filter to report actions. See [About attribution settings and models](https://www.facebook.com/business/help/460276478298895?id=561906377587030) for examples. The `default` option means `["7d_view","1d_click"]`. |
| `action_breakdowns`  list<enum{action\_device, conversion\_destination, matched\_persona\_id, matched\_persona\_name, signal\_source\_bucket, standard\_event\_content\_type, action\_canvas\_component\_name, action\_carousel\_card\_id, action\_carousel\_card\_name, action\_destination, action\_reaction, action\_target\_id, action\_type, action\_video\_sound, action\_video\_type, is\_business\_ai\_assisted}> | Default value: `Vec`  How to break down action results. Supports more than one breakdowns. Default value is ["action\_type"]  Note: you must also include `actions` field whenever `action_breakdowns` is specified. |
| `action_report_time`  enum{impression, conversion, mixed, lifetime} | Determines the report time of action stats. For example, if a person saw the ad on Jan 1st but converted on Jan 2nd, when you query the API with `action_report_time=impression`, you see a conversion on Jan 1st. When you query the API with `action_report_time=conversion`, you see a conversion on Jan 2nd |
| `breakdowns`  list<enum{ad\_extension\_domain, ad\_extension\_url, ad\_format\_asset, age, app\_id, body\_asset, breakdown\_ad\_objective, breakdown\_reporting\_ad\_id, call\_to\_action\_asset, coarse\_conversion\_value, comscore\_market, country, creative\_automation\_asset\_id, creative\_relaxation\_asset\_type, crm\_advertiser\_l12\_territory\_ids, crm\_advertiser\_subvertical\_id, crm\_advertiser\_vertical\_id, crm\_ult\_advertiser\_id, description\_asset, existing\_post\_id, fidelity\_type, flexible\_format\_asset\_type, gen\_ai\_asset\_type, gender, hsid, image\_asset, impression\_device, instagram\_ads\_follow\_type, instagram\_ads\_instagram\_media\_product\_type, instagram\_ads\_time\_since\_creation\_bucket, internal\_campaign\_id, is\_auto\_advance, is\_conversion\_id\_modeled, is\_rendered\_as\_delayed\_skip\_ad, landing\_destination, link\_url\_asset, mdsa\_landing\_destination, media\_asset\_url, media\_creator, media\_destination\_url, media\_format, media\_origin\_url, media\_text\_content, media\_type, pa\_creator\_ig\_handle, postback\_sequence\_index, product\_brand\_breakdown, product\_category\_breakdown, product\_custom\_label\_0\_breakdown, product\_custom\_label\_1\_breakdown, product\_custom\_label\_2\_breakdown, product\_custom\_label\_3\_breakdown, product\_custom\_label\_4\_breakdown, product\_group\_content\_id\_breakdown, product\_id, redownload, region, rta\_ugc\_topic, skan\_campaign\_id, skan\_conversion\_id, skan\_version, sot\_attribution\_model\_type, sot\_attribution\_window, sot\_channel, sot\_event\_type, sot\_source, title\_asset, user\_persona\_id, user\_persona\_name, video\_asset, zip, rule\_set\_id, rule\_set\_name, dma, frequency\_value, overlap\_segment, hourly\_stats\_aggregated\_by\_advertiser\_time\_zone, hourly\_stats\_aggregated\_by\_audience\_time\_zone, mmm, place\_page\_id, publisher\_platform, platform\_position, device\_platform, standard\_event\_content\_type, conversion\_destination, signal\_source\_bucket, reels\_trending\_topic, marketing\_messages\_btn\_name, impression\_view\_time\_advertiser\_hour\_v2}> | How to break down the result. For more than one breakdown, only certain combinations are available: See "Combining Breakdowns" in the Breakdowns page. The option `impression_device` cannot be used by itself |
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | Default value: `last_30d`  Represents a relative time range. This field is ignored if `time_range` or `time_ranges` is specified |
| `default_summary`  boolean | Default value: `false`  Determine whether to return a summary. If `summary` is set, this param is ignored; otherwise, a summary section with the same fields as specified by `fields` is included in the summary section |
| `export_columns`  list<string> | Select fields on the exporting report file. It is an optional param. Exporting columns are equal to the param fields if you leave this param blank |
| `export_format`  string | Set the format of exporting report file. If the export\_format is set, Report file is asyncrhonizely generated. It expects ["xls", "csv"]. |
| `export_name`  string | Set the file name of the exporting report. |
| `fields`  list<string> | Fields to be retrieved. Default behavior is to return a list of most used fields |
| `filtering`  list<Filter Object> | Default value: `Vec`  Filters on the report data. This parameter is an array of filter objects |
| `field`  string | Required |
| `operator`  enum {EQUAL, NOT\_EQUAL, GREATER\_THAN, GREATER\_THAN\_OR\_EQUAL, LESS\_THAN, LESS\_THAN\_OR\_EQUAL, IN\_RANGE, NOT\_IN\_RANGE, CONTAIN, NOT\_CONTAIN, CONTAINS\_ANY, CONTAINS\_ALL, NOT\_CONTAINS\_ANY, STEM\_MATCH, IN, NOT\_IN, STARTS\_WITH, ENDS\_WITH, ANY, ALL, AFTER, BEFORE, ON\_OR\_AFTER, ON\_OR\_BEFORE, NONE, TOP} | Required |
| `value`  string | Required |
| `graph_cache`  boolean | Default value: `true`  [internal use only] This param controls whether the the Graph API level cache should be used for insights endpoint |
| `level`  enum {ad, adset, campaign, account} | Represents the level of result |
| `limit`  integer | limit |
| `product_id_limit`  integer | Maximum number of product ids to be returned for each ad when breakdown by `product_id`. |
| `sort`  list<string> | Default value: `Vec`  Field to sort the result, and direction of sorting. You can specify sorting direction by appending "\_ascending" or "\_descending" to the sort field. For example, "reach\_descending". For actions, you can sort by action type in form of "actions:<action\_type>". For example, ["actions:link\_click\_ascending"]. This array supports no more than one element. By default, the sorting direction is ascending |
| `summary`  list<string> | If this param is used, a summary section is included, with the fields listed in this param |
| `summary_action_breakdowns`  list<enum{action\_device, conversion\_destination, matched\_persona\_id, matched\_persona\_name, signal\_source\_bucket, standard\_event\_content\_type, action\_canvas\_component\_name, action\_carousel\_card\_id, action\_carousel\_card\_name, action\_destination, action\_reaction, action\_target\_id, action\_type, action\_video\_sound, action\_video\_type, is\_business\_ai\_assisted}> | Default value: `Vec`  Similar to `action_breakdowns`, but applies to summary. Default value is ["action\_type"] |
| `time_increment`  enum{monthly, all\_days} or integer | Default value: `all_days`  If it is an integer, it is the number of days from 1 to 90. After you pick a reporting period by using `time_range` or `date_preset`, you may choose to have the results for the whole period, or have results for smaller time slices. If "all\_days" is used, it means one result set for the whole period. If "monthly" is used, you get one result set for each calendar month in the given period. Or you can have one result set for each N-day period specified by this param. This param is ignored if `time_ranges` is specified |
| `time_range`  {'since':YYYY-MM-DD,'until':YYYY-MM-DD} | A single time range object. UNIX timestamp not supported. This param is ignored if `time_ranges` is provided |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |
| `time_ranges`  list<{'since':YYYY-MM-DD,'until':YYYY-MM-DD}> | Array of time range objects. Time ranges can overlap, for example to return cumulative insights. Each time range has one result set. You cannot have more granular results with `time_increment` setting in this case.If `time_ranges` is specified, `date_preset`, `time_range` and `time_increment` are ignored |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |
| `use_account_attribution_setting`  boolean | Default value: `false`  When this parameter is set to true, your ads results are shown using the attribution settings defined for the ad account |
| `use_unified_attribution_setting`  boolean | When this parameter is set to `true`, your ads results will be shown using unified attribution settings defined at ad set level and parameter `use_account_attribution_setting` will be ignored.   **Note:** Please set this to `true` to get the same behavior as in the Ads Manager. |

### Return Type

Struct {

`report_run_id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 190 | Invalid OAuth 2.0 Access Token |
| 3018 | The start date of the time range cannot be beyond 37 months from the current date |
| 200 | Permissions error |
| 2500 | Error parsing graph query |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
