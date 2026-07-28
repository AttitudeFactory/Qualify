Graph API Version

[v25.0](#)

# Campaign

A campaign is the highest level organizational structure within an ad account and should represent a single objective for an advertiser, for example, to drive page post engagement. Setting objective of the campaign will enforce validation on any ads added to the campaign to ensure they also have the correct objective.

The `date_preset = lifetime` parameter is disabled in Graph API v10.0 and replaced with `date_preset = maximum`, which returns a maximum of 37 months of data. For v9.0 and below, `date_preset = maximum` will be enabled on May 25, 2021, and any `lifetime` calls will default to `maximum` and return only 37 months of data.

### Limits

* You can only create 200 ad sets per ad campaign. [Learn more about the ad campaign structure](/docs/marketing-api/reference/ad-campaign-group).
* If your campaign has more than 70 ad sets and uses [Campaign Budget Optimization](/docs/marketing-api/bidding/guides/campaign-budget-optimization), you are not able to edit your current bid strategy or turn off CBO. [Learn more in the Business Help Center](https://www.facebook.com/business/help/519856662172206).

### New Required Field for All Campaigns

All businesses using the Marketing API must identify whether or not new and edited campaigns belong to a [Special Ad Category](/docs/marketing-api/audiences/special-ad-category). Current available categories are: [housing, employment, credit](/docs/marketing-api/audiences/special-ad-category/#context), or issues, elections, and politics. Businesses whose ads do not belong to a Special Ad Category must indicate NONE or send an empty array in the `special_ad_categories` field.

Businesses running **housing**, **employment**, or **credit** ads must comply with [targeting and audience restrictions](/docs/marketing-api/audiences/reference/targeting-restrictions). Targeting for ads about social issues, elections or politics are not affected by the `special_ad_categories` label.

As of **Marketing API 7.0**, the `special_ad_category` parameter on the [`POST /act_<ad_account_id>/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/#Creating) endpoint has been deprecated and replaced with a new `special_ad_categories` parameter. The new `special_ad_categories` parameter is required and accepts an array.

If you use the `special_ad_category` parameter, it will still return a string, but you should use `GET /{campaign-id}?fields=special_ad_categories` to get an array back. Refer to [Special Ad Category](https://developers.facebook.com/docs/marketing-api/audiences/special-ad-category/) for additional information.

## Reading

A campaign is a grouping of ad sets which are organized by the same business objective. Each campaign has an objective that must be valid across the ad sets within that campaign.

After your ads begin delivering, you can query stats for ad campaigns. The statistics returned will be unique stats, deduped across the ad sets. You can also get reports and statistics for all ad sets and ads in an campaign simultaneously.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_Campaign%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_Campaign} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_Campaign}',
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
    "...?fields={fieldname_of_type_Campaign}",
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
    "...?fields={fieldname_of_type_Campaign}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_Campaign}"
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
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | Date Preset |
| `time_range`  {'since':YYYY-MM-DD,'until':YYYY-MM-DD} | Time Range. Note if time range is invalid, it will be ignored. |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | Campaign's ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `account_id`  numeric string | ID of the ad account that owns this campaign |
| `adlabels`  [list<AdLabel>](https://developers.facebook.com/docs/marketing-api/reference/ad-label/) | Ad Labels associated with this campaign |
| `bid_strategy`  enum {LOWEST\_COST\_WITHOUT\_CAP, LOWEST\_COST\_WITH\_BID\_CAP, COST\_CAP, LOWEST\_COST\_WITH\_MIN\_ROAS} | Bid strategy for this campaign when you enable campaign budget optimization and when you use `AUCTION` as your buying type:  `LOWEST_COST_WITHOUT_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` without limiting your bid amount. This is the best strategy to select if you care most about cost efficiency. However, note that it may be harder to get stable average costs as you spend. Note: this strategy is also known as *automatic bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  `LOWEST_COST_WITH_BID_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` while limiting actual bid to a specified amount. Get specified bid cap in the `bid_amount` field for each ad set in this ad campaign. This strategy is known as *manual maximum-cost bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  `COST_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` while limiting actual average cost per optimization event to a specified amount. Get specified cost cap in the `bid_amount` field for each ad set in this ad campaign. Learn more in [Ads Help Center, About bid strategies: Cost Cap](https://www.facebook.com/business/help/272336376749096?id=2196356200683573). Notes:   * If you do not enable campaign budget optimization, you should get `bid_strategy` at the ad set level. * `TARGET_COST` bidding strategy has been deprecated with [Marketing API v9](/docs/graph-api/changelog/version9.0). |
| `boosted_object_id`  numeric string | The Boosted Object this campaign has associated, if any |
| `brand_lift_studies`  [list<AdStudy>](https://developers.facebook.com/docs/marketing-api/reference/ad-study/) | Automated Brand Lift V2 studies for this ad set. |
| `budget_rebalance_flag`  bool | Whether to automatically rebalance budgets daily for all the adsets under this campaign. [This has been deprecated on Marketing API V7.0](/docs/graph-api/changelog/version7.0#deprecations). |
| `budget_remaining`  numeric string | Remaining budget |
| `buying_type`  string | Buying type, possible values are:  `AUCTION`: default `RESERVED`: for [reach and frequency ads](/docs/marketing-api/reachandfrequency) [Reach and Frequency](/docs/marketing-api/reachandfrequency) is disabled for [housing, employment and credit ads](/docs/marketing-api/special-ad-category). |
| `campaign_group_active_time`  numeric string | campaign\_group\_active\_time this is only for Internal, This will have the active running length of Campaign Groups |
| `can_create_brand_lift_study`  bool | If we can create a new automated brand lift study for the ad set. |
| `can_use_spend_cap`  bool | Whether the campaign can set the spend cap |
| `configured_status`  enum {ACTIVE, PAUSED, DELETED, ARCHIVED} | If this status is `PAUSED`, all its active ad sets and ads will be paused and have an effective status `CAMPAIGN_PAUSED`. Prefer using 'status' instead of this. |
| `created_time`  datetime | Created Time |
| `daily_budget`  numeric string | The daily budget of the campaign |
| `effective_status`  enum {ACTIVE, PAUSED, DELETED, ARCHIVED, IN\_PROCESS, WITH\_ISSUES} | IN\_PROCESS is available for version 4.0 or higher |
| `has_secondary_skadnetwork_reporting`  bool | has\_secondary\_skadnetwork\_reporting |
| `is_adset_budget_sharing_enabled`  bool | Whether the child ad sets are managed under ad set budget sharing |
| `is_budget_schedule_enabled`  bool | Whether budget scheduling is enabled for the campaign group |
| `is_reels_trending_ads_enabled`  bool | is\_reels\_trending\_ads\_enabled |
| `is_skadnetwork_attribution`  bool | When set to `true` Indicates that the campaign will include SKAdNetwork, iOS 14+. |
| `issues_info`  [list<AdCampaignIssuesInfo>](https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-issues-info/) | Issues for this campaign that prevented it from deliverying |
| `last_budget_toggling_time`  datetime | Last budget toggling time |
| `lifetime_budget`  numeric string | The lifetime budget of the campaign |
| `name`  string | Campaign's name |
| `objective`  string | Campaign's objective  See the [Outcome Ad-Driven Experience Objective Validation](#odax) section below for more information. |
| `pacing_type`  list<string> | Defines pacing type of the campaign. The value is an array of options: "standard". |
| `primary_attribution`  enum | primary\_attribution |
| `promoted_object`  [AdPromotedObject](https://developers.facebook.com/docs/marketing-api/reference/ad-promoted-object/) | The object this campaign is promoting across all its ads |
| `smart_promotion_type`  enum | Smart Promotion Type. guided\_creation or smart\_app\_promotion(the choice under APP\_INSTALLS objective). |
| `source_campaign`  [Campaign](https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/) | The source campaign that this campaign is copied from |
| `source_campaign_id`  numeric string | The source campaign id that this campaign is copied from |
| `special_ad_categories`  list<enum> | special ad categories |
| `special_ad_category`  enum | The campaign's Special Ad Category. One of `HOUSING`, `EMPLOYMENT`, `CREDIT`, or `NONE`. |
| `special_ad_category_country`  list<enum> | Country field for Special Ad Category. |
| `spend_cap`  numeric string | A spend cap for the campaign, such that it will not spend more than this cap. Expressed as integer value of the subunit in your currency. |
| `start_time`  datetime | Merging of `start_time`s for the ad sets belonging to this campaign. At the campaign level, `start_time` is a read only field. You can setup `start_time` at the ad set level. |
| `status`  enum {ACTIVE, PAUSED, DELETED, ARCHIVED} | If this status is `PAUSED`, all its active ad sets and ads will be paused and have an effective status `CAMPAIGN_PAUSED`. The field returns the same value as 'configured\_status', and is the suggested one to use. |
| `stop_time`  datetime | Merging of `stop_time`s for the ad sets belonging to this campaign, if available. At the campaign level, `stop_time` is a read only field. You can setup `stop_time` at the ad set level. |
| `topline_id`  numeric string | Topline ID |
| `updated_time`  datetime | Updated Time. If you update `spend_cap` or daily budget or lifetime budget, this will not automatically update this field. |

### Edges

| Edge | Description |
| --- | --- |
| [`ad_studies`](/docs/marketing-api/reference/ad-campaign-group/ad_studies/)  Edge<AdStudy> | The ad studies containing this campaign |
| [`adrules_governed`](/docs/marketing-api/reference/ad-campaign-group/adrules_governed/)  Edge<AdRule> | Ad rules that govern this campaign - by default, this only returns rules that either directly mention the campaign by id or indirectly through the set entity\_type |
| [`ads`](/docs/marketing-api/reference/ad-campaign-group/ads/)  Edge<Adgroup> | Ads under this campaign |
| [`adsets`](/docs/marketing-api/reference/ad-campaign-group/adsets/)  Edge<AdCampaign> | The ad sets under this campaign |
| [`copies`](/docs/marketing-api/reference/ad-campaign-group/copies/)  Edge<AdCampaignGroup> | The copies of this campaign |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 613 | Calls to this api have exceeded the rate limit. |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |
| 2500 | Error parsing graph query |
| 3018 | The start date of the time range cannot be beyond 37 months from the current date |
| 200 | Permissions error |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |

## Creating

You can make a POST request to `async_batch_requests` edge from the following paths:

* [`/act_{ad_account_id}/async_batch_requests`](/docs/marketing-api/reference/ad-account/async_batch_requests/)

When posting to this edge, a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `adbatch`  list<Object> | JSON encoded batch reqeust  Required |
| `name`  string | Required |
| `relative_url`  string | Required |
| `body`  UTF-8 encoded string | Required |
| `name`  UTF-8 encoded string | Name of the batch request for tracking purposes.  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 194 | Missing at least one required parameter |
| 100 | Invalid parameter |
| 2500 | Error parsing graph query |

You can make a POST request to `copies` edge from the following paths:

* [`/{campaign_id}/copies`](/docs/marketing-api/reference/ad-campaign-group/copies/)

When posting to this edge, a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `deep_copy`  boolean | Default value: `false`  Whether to copy all the child ads. Limits: the total number of children ads to copy should not exceed 3 for a synchronous call and 51 for an asynchronous call. |
| `end_time`  datetime | For deep copy, the end time of the sets under the copied campaign, e.g. `2015-03-12 23:59:59-07:00` or `2015-03-12 23:59:59 PDT`. UTC UNIX timestamp. When creating a set with a daily budget, specify `end_time=0` to set the set to be ongoing without end date. If not set, the copied sets will inherit the end time from the original set |
| `parameter_overrides`  Campaign spec | parameter\_overrides |
| `rename_options`  JSON or object-like arrays | Rename options |
| `rename_strategy`  enum {DEEP\_RENAME, ONLY\_TOP\_LEVEL\_RENAME, NO\_RENAME} | Default value: `ONLY_TOP_LEVEL_RENAME`  `DEEP_RENAME`: will change this object's name and children's names in the copied object. `ONLY_TOP_LEVEL_RENAME`: will change the this object's name but won't change the children's name in the copied object. `NO_RENAME`: will change no name in the copied object |
| `rename_prefix`  string | A prefix to copy names. Defaults to null if not provided. |
| `rename_suffix`  string | A suffix to copy names. Defaults to null if not provided and appends a localized string of `- Copy` based on the ad account locale. |
| `start_time`  datetime | For deep copy, the start time of the sets under the copied campaign, e.g. `2015-03-12 23:59:59-07:00` or `2015-03-12 23:59:59 PDT`. UTC UNIX timestamp. If not set, the copied sets will inherit the start time from the original set |
| `status_option`  enum {ACTIVE, PAUSED, INHERITED\_FROM\_SOURCE} | Default value: `PAUSED`  `ACTIVE`: the copied campaign will have active status. `PAUSED`: the copied campaign will have paused status. `INHERITED_FROM_SOURCE`: the copied campaign will have the parent status. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `copied_campaign_id` in the return type.

Struct {

`copied_campaign_id`: numeric string,

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
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |

You can make a POST request to `campaigns` edge from the following paths:

* [`/act_{ad_account_id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/)

When posting to this edge, a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) will be created.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=POST&path=act_%3CAD_ACCOUNT_ID%3E%2Fcampaigns%3Fname%3DMy%2Bcampaign%26objective%3DOUTCOME_TRAFFIC%26status%3DPAUSED%26special_ad_categories%3D%255B%255D%26is_adset_budget_sharing_enabled%3D0&version=v25.0)

```
POST /v25.0/act_<AD_ACCOUNT_ID>/campaigns HTTP/1.1
Host: graph.facebook.com

name=My+campaign&objective=OUTCOME_TRAFFIC&status=PAUSED&special_ad_categories=%5B%5D&is_adset_budget_sharing_enabled=0
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/act_<AD_ACCOUNT_ID>/campaigns',
    array (
      'name' => 'My campaign',
      'objective' => 'OUTCOME_TRAFFIC',
      'status' => 'PAUSED',
      'special_ad_categories' => '[]',
      'is_adset_budget_sharing_enabled' => '0',
    ),
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
    "/act_<AD_ACCOUNT_ID>/campaigns",
    "POST",
    {
        "name": "My campaign",
        "objective": "OUTCOME_TRAFFIC",
        "status": "PAUSED",
        "special_ad_categories": "[]",
        "is_adset_budget_sharing_enabled": "0"
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
params.putString("name", "My campaign");
params.putString("objective", "OUTCOME_TRAFFIC");
params.putString("status", "PAUSED");
params.putString("special_ad_categories", "[]");
params.putString("is_adset_budget_sharing_enabled", "0");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/act_<AD_ACCOUNT_ID>/campaigns",
    params,
    HttpMethod.POST,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"name": @"My campaign",
  @"objective": @"OUTCOME_TRAFFIC",
  @"status": @"PAUSED",
  @"special_ad_categories": @"[]",
  @"is_adset_budget_sharing_enabled": @"0",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/act_<AD_ACCOUNT_ID>/campaigns"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

```
curl -X POST \
  -F 'name="My campaign"' \
  -F 'objective="OUTCOME_TRAFFIC"' \
  -F 'status="PAUSED"' \
  -F 'special_ad_categories=[]' \
  -F 'is_adset_budget_sharing_enabled=0' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/campaigns
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `adlabels`  list<Object> | [Ad Labels](/docs/marketing-api/reference/ad-label) associated with this campaign |
| `bid_strategy`  enum{LOWEST\_COST\_WITHOUT\_CAP, LOWEST\_COST\_WITH\_BID\_CAP, COST\_CAP, LOWEST\_COST\_WITH\_MIN\_ROAS} | Choose bid strategy for this campaign to suit your specific business goals. Each strategy has tradeoffs and may be available for certain `optimization_goal`s:  `LOWEST_COST_WITHOUT_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` without limiting your bid amount. This is the best strategy if you care most about cost efficiency. However with this strategy it may be harder to get stable average costs as you spend. This strategy is also known as *automatic bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  `LOWEST_COST_WITH_BID_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` while limiting actual bid to your specified amount. With a bid cap you have more control over your cost per actual optimization event. However if you set a limit which is too low you may get less ads delivery. If you select this, you must provide a bid cap in the `bid_amount` field for each ad set in this ad campaign. Note: during creation this is the default bid strategy if you don't specify. This strategy is also known as *manual maximum-cost bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  **Notes:**   * If you do not enable campaign budget optimization, you should set `bid_strategy` at ad set level. * `TARGET_COST` bidding strategy has been deprecated with [Marketing API v9](/docs/graph-api/changelog/version9.0). |
| `budget_schedule_specs`  list<JSON or object-like arrays> | Initial high demand periods to be created with the campaign.  Provide list of `time_start`, `time_end`,`budget_value`, and `budget_value_type`. For example, -F 'budget\_schedule\_specs=[{  "time\_start":1699081200,  "time\_end":1699167600,  "budget\_value":100,  "budget\_value\_type":"ABSOLUTE"  }]'   See [High Demand Period](https://developers.facebook.com/docs/graph-api/reference/high-demand-period/) for more details on each field. |
| `id`  int64 |  |
| `time_start`  datetime |  |
| `time_end`  datetime |  |
| `budget_value`  int64 |  |
| `budget_value_type`  enum{ABSOLUTE, MULTIPLIER} |  |
| `recurrence_type`  enum{ONE\_TIME, WEEKLY} |  |
| `weekly_schedule`  list<JSON or object-like arrays> |  |
| `days`  list<int64> |  |
| `minute_start`  int64 |  |
| `minute_end`  int64 |  |
| `timezone_type`  string |  |
| `buying_type`  string | Default value: `AUCTION`  This field will help Facebook make optimizations to delivery, pricing, and limits. All ad sets in this campaign must match the buying type. Possible values are:  `AUCTION` (default) `RESERVED` (for [reach and frequency ads](/docs/marketing-api/reachandfrequency)). |
| `campaign_optimization_type`  enum{NONE, ICO\_ONLY} | campaign\_optimization\_type |
| `daily_budget`  int64 | Daily budget of this campaign. All adsets under this campaign will share this budget. You can either set budget at the campaign level or at the adset level, not both. |
| `execution_options`  list<enum{validate\_only, include\_recommendations}> | Default value: `Set`  An execution setting  `validate_only`: when this option is specified, the API call will not perform the mutation but will run through the validation rules against values of each field.  `include_recommendations`: this option cannot be used by itself. When this option is used, recommendations for ad object's configuration will be included. A separate section [recommendations](/docs/marketing-api/reference/ad-recommendation) will be included in the response, but only if recommendations for this specification exist. If the call passes validation or review, response will be `{"success": true}`. If the call does not pass, an error will be returned with more details. These options can be used to improve any UI to display errors to the user much sooner, e.g. as soon as a new value is typed into any field corresponding to this ad object, rather than at the upload/save stage, or after review. |
| `is_meta_moment_maker_enabled`  boolean | is\_meta\_moment\_maker\_enabled |
| `is_skadnetwork_attribution`  boolean | To create an iOS 14 campaign, enable SKAdNetwork attribution for this campaign. |
| `is_using_l3_schedule`  boolean | is\_using\_l3\_schedule |
| `iterative_split_test_configs`  list<Object> | Array of Iterative Split Test Configs created under this campaign . |
| `lifetime_budget`  int64 | Lifetime budget of this campaign. All adsets under this campaign will share this budget. You can either set budget at the campaign level or at the adset level, not both. |
| `name`  string | Name for this campaign  Supports Emoji |
| `objective`  enum{APP\_INSTALLS, BRAND\_AWARENESS, CONVERSIONS, EVENT\_RESPONSES, LEAD\_GENERATION, LINK\_CLICKS, LOCAL\_AWARENESS, MESSAGES, OFFER\_CLAIMS, OUTCOME\_APP\_PROMOTION, OUTCOME\_AWARENESS, OUTCOME\_ENGAGEMENT, OUTCOME\_LEADS, OUTCOME\_SALES, OUTCOME\_TRAFFIC, PAGE\_LIKES, POST\_ENGAGEMENT, PRODUCT\_CATALOG\_SALES, REACH, STORE\_VISITS, VIDEO\_VIEWS} | Campaign's objective. If it is specified the API will validate that any ads created under the campaign match that objective.  Currently, with `BRAND_AWARENESS` objective, all creatives should be either only images or only videos, not mixed.   See [Outcome Ad-Driven Experience Objective Validation](/docs/marketing-api/reference/ad-campaign-group/#odax) for more information. |
| `promoted_object`  Object | The object this campaign is promoting across all its ads. It’s required for Meta iOS 14+ app promotion (SKAdNetwork or Aggregated Event Measurement) campaign creation. Only `product_catalog_id` is used at the ad set level. |
| `application_id`  int | The ID of a Facebook Application. Usually related to mobile or canvas games being promoted on Facebook for installs or engagement |
| `pixel_id`  numeric string or integer | The ID of a Facebook conversion pixel. Used with offsite conversion campaigns. |
| `custom_event_type`  enum{AD\_IMPRESSION, RATE, TUTORIAL\_COMPLETION, CONTACT, CUSTOMIZE\_PRODUCT, DONATE, FIND\_LOCATION, SCHEDULE, START\_TRIAL, SUBMIT\_APPLICATION, SUBSCRIBE, ADD\_TO\_CART, ADD\_TO\_WISHLIST, INITIATED\_CHECKOUT, ADD\_PAYMENT\_INFO, PURCHASE, LEAD, COMPLETE\_REGISTRATION, CONTENT\_VIEW, SEARCH, SERVICE\_BOOKING\_REQUEST, MESSAGING\_CONVERSATION\_STARTED\_7D, LEVEL\_ACHIEVED, ACHIEVEMENT\_UNLOCKED, SPENT\_CREDITS, LISTING\_INTERACTION, D2\_RETENTION, D7\_RETENTION, OTHER} | The event from an App Event of a mobile app, not in the standard event list. |
| `object_store_url`  URL | The uri of the mobile / digital store where an application can be bought / downloaded. This is platform specific. When combined with the "application\_id" this uniquely specifies an object which can be the subject of a Facebook advertising campaign. |
| `object_store_urls`  list<URL> | The vec of uri of the mobile / digital store where an application can be bought / downloaded. This is platform specific. When combined with the "application\_id" this uniquely specifies an object which can be the subject of a Facebook advertising campaign. |
| `offer_id`  numeric string or integer | The ID of an Offer from a Facebook Page. |
| `page_id`  Page ID | The ID of a Facebook Page |
| `product_catalog_id`  numeric string or integer | The ID of a Product Catalog. Used with [Dynamic Product Ads](/docs/marketing-api/dynamic-product-ads). |
| `product_item_id`  numeric string or integer | The ID of the product item. |
| `job_listing_id`  numeric string or integer | The ID of the marketplace job listing. |
| `instagram_profile_id`  numeric string or integer | The ID of the instagram profile id. |
| `instagram_actor_id`  numeric string or integer | The ID of the L2-selected Instagram actor for UPV ads. |
| `product_set_id`  numeric string or integer | The ID of a Product Set within an Ad Set level Product Catalog. Used with [Dynamic Product Ads](/docs/marketing-api/dynamic-product-ads). |
| `event_id`  numeric string or integer | The ID of a Facebook Event |
| `offline_conversion_data_set_id`  numeric string or integer | The ID of the offline dataset. |
| `fundraiser_campaign_id`  numeric string or integer | The ID of the fundraiser campaign. |
| `custom_event_str`  string | The event from an App Event of a mobile app, not in the standard event list. |
| `mcme_conversion_id`  numeric string or integer | The ID of a MCME conversion. |
| `conversion_goal_id`  numeric string or integer | The ID of a Conversion Goal. |
| `offsite_conversion_event_id`  numeric string or integer | The ID of a Offsite Conversion Event |
| `boosted_product_set_id`  numeric string or integer | The ID of the Boosted Product Set within an Ad Set level Product Catalog. Should only be present when the advertiser has opted into Product Set Boosting. |
| `lead_ads_form_event_source_type`  enum{inferred, meta\_source, offsite\_crm, offsite\_web, onsite\_crm, onsite\_crm\_single\_event, onsite\_clo\_dep\_aet, onsite\_web, onsite\_p2b\_call, onsite\_messaging, qualified\_lead\_file} | The event source of lead ads form. |
| `lead_ads_custom_event_type`  enum{AD\_IMPRESSION, RATE, TUTORIAL\_COMPLETION, CONTACT, CUSTOMIZE\_PRODUCT, DONATE, FIND\_LOCATION, SCHEDULE, START\_TRIAL, SUBMIT\_APPLICATION, SUBSCRIBE, ADD\_TO\_CART, ADD\_TO\_WISHLIST, INITIATED\_CHECKOUT, ADD\_PAYMENT\_INFO, PURCHASE, LEAD, COMPLETE\_REGISTRATION, CONTENT\_VIEW, SEARCH, SERVICE\_BOOKING\_REQUEST, MESSAGING\_CONVERSATION\_STARTED\_7D, LEVEL\_ACHIEVED, ACHIEVEMENT\_UNLOCKED, SPENT\_CREDITS, LISTING\_INTERACTION, D2\_RETENTION, D7\_RETENTION, OTHER} | The event from an App Event of a mobile app, not in the standard event list. |
| `lead_ads_custom_event_str`  string | The event from an App Event of a mobile app, not in the standard event list. |
| `lead_ads_offsite_conversion_type`  enum{default, clo} | The offsite conversion type for lead ads |
| `value_semantic_type`  enum {VALUE, MARGIN, LIFETIME\_VALUE} | The semantic of the event value to be using for optimization |
| `variation`  enum {OMNI\_CHANNEL\_SHOP\_AUTOMATIC\_DATA\_COLLECTION, PRODUCT\_SET\_AND\_APP, PRODUCT\_SET\_AND\_IN\_STORE, PRODUCT\_SET\_AND\_OMNICHANNEL, PRODUCT\_SET\_AND\_PHONE\_CALL, PRODUCT\_SET\_AND\_WEBSITE, PRODUCT\_SET\_AND\_WEBSITE\_AND\_PHONE\_CALL, PRODUCT\_SET\_WEBSITE\_APP\_AND\_INSTORE} | Variation of the promoted object for a PCA ad |
| `passback_pixel_id`  numeric string or integer | ID of the pixel used for tracking passback events |
| `passback_application_id`  numeric string or integer | ID of the application used for tracking passback events |
| `product_set_optimization`  enum{enabled, disabled} | Enum defining whether or not the ad should be optimized for the promoted product set |
| `full_funnel_objective`  enum{OFFER\_CLAIMS, PAGE\_LIKES, EVENT\_RESPONSES, POST\_ENGAGEMENT, WEBSITE\_CONVERSIONS, LINK\_CLICKS, VIDEO\_VIEWS, LOCAL\_AWARENESS, PRODUCT\_CATALOG\_SALES, LEAD\_GENERATION, BRAND\_AWARENESS, STORE\_VISITS, REACH, APP\_INSTALLS, MESSAGES, OUTCOME\_AWARENESS, OUTCOME\_ENGAGEMENT, OUTCOME\_LEADS, OUTCOME\_SALES, OUTCOME\_TRAFFIC, OUTCOME\_APP\_PROMOTION} | Enum defining the full funnel objective of the campaign |
| `dataset_split_id`  numeric string or integer | ID of the dataset split used to perform additional optimization on the dataset |
| `dataset_split_ids`  array<numeric string> | IDs of the dataset splits used to perform additional optimization on the dataset |
| `lead_ads_selected_pixel_id`  numeric string or integer | The selected pixel id for lead ads conversion leads optimization |
| `custom_attribution_source_ids`  array<numeric string> | IDs of the custom attribution sources used for tracking passback events |
| `multi_event_product`  int64 | Identifies which action-to-action product the advertiser is using |
| `product_sales_channel`  enum {ONLINE, IN\_STORE, OMNI} | ProductSalesChannel of the promoted object for Omni L3 DA SBLI ads |
| `anchor_event_config`  JSON object | Configuration for anchor event in multi-event optimization campaigns |
| `multi_event_conversion_info`  JSON object | Configuration for multi-event conversion info in CLO campaigns |
| `live_video_destination`  string | The live video destination type for live video ads |
| `smart_pse_enabled`  boolean | Whether Smart Product Set Expansion is enabled for this campaign. |
| `smart_pse_setting`  enum{ENABLED, DISABLED} | Setting for Smart Product Set Expansion. Uses an enum instead of a boolean to avoid TAO null handling issues. |
| `lead_ads_follow_up_event`  enum{whatsapp\_conversations} | The selected lead follow-up event for lead ads campaigns. |
| `lead_ads_quality_volume_setting`  enum{max\_volume, more\_volume, balanced, more\_quality, max\_quality} | The quality-vs-volume preference setting for lead ads campaigns. |
| `dataset_split_specs`  array<JSON object> | MTA / Seller Optimization dataset-split definitions (key: seller\_id or brand; value: the brand / vendor\_id to optimize for). |
| `key`  string | key  Required |
| `value`  string | value  Required |
| `omnichannel_object`  Object |  |
| `app`  array<JSON object> |  |
| `pixel`  array<JSON object> | Required |
| `onsite`  array<JSON object> |  |
| `whats_app_business_phone_number_id`  numeric string or integer |  |
| `whatsapp_phone_number`  string |  |
| `source_campaign_id`  numeric string or integer | Used if a campaign has been copied. The ID from the original campaign that was copied. |
| `special_ad_categories`  array<enum {NONE, EMPLOYMENT, HOUSING, CREDIT, ISSUES\_ELECTIONS\_POLITICS, ONLINE\_GAMBLING\_AND\_GAMING, FINANCIAL\_PRODUCTS\_SERVICES}> | special\_ad\_categories  Required |
| `special_ad_category_country`  array<enum {AC, AD, AE, AF, AG, AI, AL, AM, AN, AO, AQ, AR, AS, AT, AU, AW, AX, AZ, BA, BB, BD, BE, BF, BG, BH, BI, BJ, BL, BM, BN, BO, BQ, BR, BS, BT, BV, BW, BY, BZ, CA, CC, CD, CF, CG, CH, CI, CK, CL, CM, CN, CO, CR, CU, CV, CW, CX, CY, CZ, DE, DJ, DK, DM, DO, DZ, EC, EE, EG, EH, ER, ES, ET, FI, FJ, FK, FM, FO, FR, GA, GB, GD, GE, GF, GG, GH, GI, GL, GM, GN, GP, GQ, GR, GS, GT, GU, GW, GY, HK, HM, HN, HR, HT, HU, ID, IE, IL, IM, IN, IO, IQ, IR, IS, IT, JE, JM, JO, JP, KE, KG, KH, KI, KM, KN, KP, KR, KW, KY, KZ, LA, LB, LC, LI, LK, LR, LS, LT, LU, LV, LY, MA, MC, MD, ME, MF, MG, MH, MK, ML, MM, MN, MO, MP, MQ, MR, MS, MT, MU, MV, MW, MX, MY, MZ, NA, NC, NE, NF, NG, NI, NL, NO, NP, NR, NU, NZ, OM, PA, PE, PF, PG, PH, PK, PL, PM, PN, PR, PS, PT, PW, PY, QA, RE, RO, RS, RU, RW, SA, SB, SC, SD, SE, SG, SH, SI, SJ, SK, SL, SM, SN, SO, SR, SS, ST, SV, SX, SY, SZ, TC, TD, TF, TG, TH, TJ, TK, TL, TM, TN, TO, TR, TT, TV, TW, TZ, UA, UG, UM, US, UY, UZ, VA, VC, VE, VG, VI, VN, VU, WF, WS, XK, YE, YT, ZA, ZM, ZW}> | special\_ad\_category\_country |
| `spend_cap`  int64 | A spend cap for the campaign, such that it will not spend more than this cap. Defined as integer value of subunit in your currency with a minimum value of $100 USD (or approximate local equivalent). Set the value to 922337203685478 to remove the spend cap. Not available for Reach and Frequency or Premium Self Serve campaigns |
| `start_time`  datetime | start\_time |
| `status`  enum{ACTIVE, PAUSED, DELETED, ARCHIVED} | Only `ACTIVE` and `PAUSED` are valid during creation. Other statuses can be used for update. If it is set to `PAUSED`, its active child objects will be paused and have an effective status `CAMPAIGN_PAUSED`. |
| `stop_time`  datetime | stop\_time |
| `topline_id`  numeric string or integer | Topline ID |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 613 | Calls to this api have exceeded the rate limit. |
| 200 | Permissions error |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 190 | Invalid OAuth 2.0 Access Token |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 300 | Edit failure |

## Updating

You can update a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) by making a POST request to [`/{campaign_id}`](/docs/marketing-api/reference/ad-campaign-group/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `adlabels`  list<Object> | [Ad Labels](/docs/marketing-api/reference/ad-label) associated with this campaign |
| `adset_bid_amounts`  JSON object {numeric string : int64} | A map of child adset IDs to their respective bid amounts required in the process of toggling campaign from autobid to manual bid |
| `adset_budgets`  array<JSON object> | An array of maps containing all the non-deleted child adset IDs and either daily\_budget or lifetime\_budget, required in the process of toggling between campaign budget and adset budget |
| `adset_id`  numeric string | adset\_id  Required |
| `daily_budget`  int64 | daily\_budget |
| `lifetime_budget`  int64 | lifetime\_budget |
| `bid_strategy`  enum{LOWEST\_COST\_WITHOUT\_CAP, LOWEST\_COST\_WITH\_BID\_CAP, COST\_CAP, LOWEST\_COST\_WITH\_MIN\_ROAS} | Choose bid strategy for this campaign to suit your specific business goals. Each strategy has tradeoffs and may be available for certain `optimization_goal`s:  `LOWEST_COST_WITHOUT_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` without limiting your bid amount. This is the best strategy if you care most about cost efficiency. However with this strategy it may be harder to get stable average costs as you spend. This strategy is also known as *automatic bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  `LOWEST_COST_WITH_BID_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` while limiting actual bid to your specified amount. With a bid cap you have more control over your cost per actual optimization event. However if you set a limit which is too low you may get less ads delivery. If you select this, you must provide a bid cap in the `bid_amount` field for each ad set in this ad campaign. Note: during creation this is the default bid strategy if you don't specify. This strategy is also known as *manual maximum-cost bidding*. Learn more in [Ads Help Center, About bid strategies: Lowest cost](https://www.facebook.com/business/help/721453268045071).  `COST_CAP`: Designed to get the most results for your budget based on your ad set `optimization_goal` while limiting actual average cost per optimization event to a specified amount. Get specified cost cap in the `bid_amount` field for each ad set in this ad campaign. Learn more in [Ads Help Center, About bid strategies: Cost Cap](https://www.facebook.com/business/help/272336376749096?id=2196356200683573).  Notes:   * If you do not enable campaign budget optimization, you should set `bid_strategy` at ad set level. * `TARGET_COST` bidding strategy has been deprecated with [Marketing API v9](/docs/graph-api/changelog/version9.0). |
| `budget_rebalance_flag`  boolean | Whether to automatically rebalance budgets daily for all the adsets under this campaign. |
| `campaign_optimization_type`  enum{NONE, ICO\_ONLY} | campaign\_optimization\_type |
| `daily_budget`  int64 | Daily budget of this campaign. All adsets under this campaign will share this budget. You can either set budget at the campaign level or at the adset level, not both. |
| `execution_options`  list<enum{validate\_only, include\_recommendations}> | Default value: `Set`  An execution setting  `validate_only`: when this option is specified, the API call will not perform the mutation but will run through the validation rules against values of each field.  `include_recommendations`: this option cannot be used by itself. When this option is used, recommendations for ad object's configuration will be included. A separate section [recommendations](/docs/marketing-api/reference/ad-recommendation) will be included in the response, but only if recommendations for this specification exist. If the call passes validation or review, response will be `{"success": true}`. If the call does not pass, an error will be returned with more details. These options can be used to improve any UI to display errors to the user much sooner, e.g. as soon as a new value is typed into any field corresponding to this ad object, rather than at the upload/save stage, or after review. |
| `is_adset_budget_sharing_enabled`  boolean | Whether the child ad sets are managed under ad set budget sharing. With ad set budget sharing, advertisers can now share up to 20% of their budget with other ad sets in the same campaign. |
| `is_meta_moment_maker_enabled`  boolean | is\_meta\_moment\_maker\_enabled |
| `is_reels_trending_ads_enabled`  boolean | indicator for 'reels trending ads' campaign |
| `is_skadnetwork_attribution`  boolean | Flag to indicate that the campaign will be using SKAdNetwork, which also means that it will only be targeting iOS 14.x and above |
| `is_using_l3_schedule`  boolean | is\_using\_l3\_schedule |
| `iterative_split_test_configs`  list<Object> | Array of Iterative Split Test Configs created under this campaign . |
| `lifetime_budget`  int64 | Lifetime budget of this campaign. All adsets under this campaign will share this budget. You can either set budget at the campaign level or at the adset level, not both. |
| `name`  string | Name for this campaign  Supports Emoji |
| `objective`  enum{APP\_INSTALLS, BRAND\_AWARENESS, CONVERSIONS, EVENT\_RESPONSES, LEAD\_GENERATION, LINK\_CLICKS, LOCAL\_AWARENESS, MESSAGES, OFFER\_CLAIMS, OUTCOME\_APP\_PROMOTION, OUTCOME\_AWARENESS, OUTCOME\_ENGAGEMENT, OUTCOME\_LEADS, OUTCOME\_SALES, OUTCOME\_TRAFFIC, PAGE\_LIKES, POST\_ENGAGEMENT, PRODUCT\_CATALOG\_SALES, REACH, STORE\_VISITS, VIDEO\_VIEWS} | Campaign's objective. If it is specified the API will validate that any ads created under the campaign match that objective.  Currently, with `BRAND_AWARENESS` objective, all creatives should be either only images or only videos, not mixed.  See the [Outcome Ad-Driven Experience Objective Validation](#odax) section below for more information. |
| `promoted_object`  Object | The object this campaign is promoting across all its ads. Only `product_catalog_id` is used at the ad set level. |
| `application_id`  int | The ID of a Facebook Application. Usually related to mobile or canvas games being promoted on Facebook for installs or engagement |
| `pixel_id`  numeric string or integer | The ID of a Facebook conversion pixel. Used with offsite conversion campaigns. |
| `custom_event_type`  enum{AD\_IMPRESSION, RATE, TUTORIAL\_COMPLETION, CONTACT, CUSTOMIZE\_PRODUCT, DONATE, FIND\_LOCATION, SCHEDULE, START\_TRIAL, SUBMIT\_APPLICATION, SUBSCRIBE, ADD\_TO\_CART, ADD\_TO\_WISHLIST, INITIATED\_CHECKOUT, ADD\_PAYMENT\_INFO, PURCHASE, LEAD, COMPLETE\_REGISTRATION, CONTENT\_VIEW, SEARCH, SERVICE\_BOOKING\_REQUEST, MESSAGING\_CONVERSATION\_STARTED\_7D, LEVEL\_ACHIEVED, ACHIEVEMENT\_UNLOCKED, SPENT\_CREDITS, LISTING\_INTERACTION, D2\_RETENTION, D7\_RETENTION, OTHER} | The event from an App Event of a mobile app, not in the standard event list. |
| `object_store_url`  URL | The uri of the mobile / digital store where an application can be bought / downloaded. This is platform specific. When combined with the "application\_id" this uniquely specifies an object which can be the subject of a Facebook advertising campaign. |
| `object_store_urls`  list<URL> | The vec of uri of the mobile / digital store where an application can be bought / downloaded. This is platform specific. When combined with the "application\_id" this uniquely specifies an object which can be the subject of a Facebook advertising campaign. |
| `offer_id`  numeric string or integer | The ID of an Offer from a Facebook Page. |
| `page_id`  Page ID | The ID of a Facebook Page |
| `product_catalog_id`  numeric string or integer | The ID of a Product Catalog. Used with [Dynamic Product Ads](/docs/marketing-api/dynamic-product-ads). |
| `product_item_id`  numeric string or integer | The ID of the product item. |
| `job_listing_id`  numeric string or integer | The ID of the marketplace job listing. |
| `instagram_profile_id`  numeric string or integer | The ID of the instagram profile id. |
| `instagram_actor_id`  numeric string or integer | The ID of the L2-selected Instagram actor for UPV ads. |
| `product_set_id`  numeric string or integer | The ID of a Product Set within an Ad Set level Product Catalog. Used with [Dynamic Product Ads](/docs/marketing-api/dynamic-product-ads). |
| `event_id`  numeric string or integer | The ID of a Facebook Event |
| `offline_conversion_data_set_id`  numeric string or integer | The ID of the offline dataset. |
| `fundraiser_campaign_id`  numeric string or integer | The ID of the fundraiser campaign. |
| `custom_event_str`  string | The event from an App Event of a mobile app, not in the standard event list. |
| `mcme_conversion_id`  numeric string or integer | The ID of a MCME conversion. |
| `conversion_goal_id`  numeric string or integer | The ID of a Conversion Goal. |
| `offsite_conversion_event_id`  numeric string or integer | The ID of a Offsite Conversion Event |
| `boosted_product_set_id`  numeric string or integer | The ID of the Boosted Product Set within an Ad Set level Product Catalog. Should only be present when the advertiser has opted into Product Set Boosting. |
| `lead_ads_form_event_source_type`  enum{inferred, meta\_source, offsite\_crm, offsite\_web, onsite\_crm, onsite\_crm\_single\_event, onsite\_clo\_dep\_aet, onsite\_web, onsite\_p2b\_call, onsite\_messaging, qualified\_lead\_file} | The event source of lead ads form. |
| `lead_ads_custom_event_type`  enum{AD\_IMPRESSION, RATE, TUTORIAL\_COMPLETION, CONTACT, CUSTOMIZE\_PRODUCT, DONATE, FIND\_LOCATION, SCHEDULE, START\_TRIAL, SUBMIT\_APPLICATION, SUBSCRIBE, ADD\_TO\_CART, ADD\_TO\_WISHLIST, INITIATED\_CHECKOUT, ADD\_PAYMENT\_INFO, PURCHASE, LEAD, COMPLETE\_REGISTRATION, CONTENT\_VIEW, SEARCH, SERVICE\_BOOKING\_REQUEST, MESSAGING\_CONVERSATION\_STARTED\_7D, LEVEL\_ACHIEVED, ACHIEVEMENT\_UNLOCKED, SPENT\_CREDITS, LISTING\_INTERACTION, D2\_RETENTION, D7\_RETENTION, OTHER} | The event from an App Event of a mobile app, not in the standard event list. |
| `lead_ads_custom_event_str`  string | The event from an App Event of a mobile app, not in the standard event list. |
| `lead_ads_offsite_conversion_type`  enum{default, clo} | The offsite conversion type for lead ads |
| `value_semantic_type`  enum {VALUE, MARGIN, LIFETIME\_VALUE} | The semantic of the event value to be using for optimization |
| `variation`  enum {OMNI\_CHANNEL\_SHOP\_AUTOMATIC\_DATA\_COLLECTION, PRODUCT\_SET\_AND\_APP, PRODUCT\_SET\_AND\_IN\_STORE, PRODUCT\_SET\_AND\_OMNICHANNEL, PRODUCT\_SET\_AND\_PHONE\_CALL, PRODUCT\_SET\_AND\_WEBSITE, PRODUCT\_SET\_AND\_WEBSITE\_AND\_PHONE\_CALL, PRODUCT\_SET\_WEBSITE\_APP\_AND\_INSTORE} | Variation of the promoted object for a PCA ad |
| `passback_pixel_id`  numeric string or integer | ID of the pixel used for tracking passback events |
| `passback_application_id`  numeric string or integer | ID of the application used for tracking passback events |
| `product_set_optimization`  enum{enabled, disabled} | Enum defining whether or not the ad should be optimized for the promoted product set |
| `full_funnel_objective`  enum{OFFER\_CLAIMS, PAGE\_LIKES, EVENT\_RESPONSES, POST\_ENGAGEMENT, WEBSITE\_CONVERSIONS, LINK\_CLICKS, VIDEO\_VIEWS, LOCAL\_AWARENESS, PRODUCT\_CATALOG\_SALES, LEAD\_GENERATION, BRAND\_AWARENESS, STORE\_VISITS, REACH, APP\_INSTALLS, MESSAGES, OUTCOME\_AWARENESS, OUTCOME\_ENGAGEMENT, OUTCOME\_LEADS, OUTCOME\_SALES, OUTCOME\_TRAFFIC, OUTCOME\_APP\_PROMOTION} | Enum defining the full funnel objective of the campaign |
| `dataset_split_id`  numeric string or integer | ID of the dataset split used to perform additional optimization on the dataset |
| `dataset_split_ids`  array<numeric string> | IDs of the dataset splits used to perform additional optimization on the dataset |
| `lead_ads_selected_pixel_id`  numeric string or integer | The selected pixel id for lead ads conversion leads optimization |
| `custom_attribution_source_ids`  array<numeric string> | IDs of the custom attribution sources used for tracking passback events |
| `multi_event_product`  int64 | Identifies which action-to-action product the advertiser is using |
| `product_sales_channel`  enum {ONLINE, IN\_STORE, OMNI} | ProductSalesChannel of the promoted object for Omni L3 DA SBLI ads |
| `anchor_event_config`  JSON object | Configuration for anchor event in multi-event optimization campaigns |
| `multi_event_conversion_info`  JSON object | Configuration for multi-event conversion info in CLO campaigns |
| `live_video_destination`  string | The live video destination type for live video ads |
| `smart_pse_enabled`  boolean | Whether Smart Product Set Expansion is enabled for this campaign. |
| `smart_pse_setting`  enum{ENABLED, DISABLED} | Setting for Smart Product Set Expansion. Uses an enum instead of a boolean to avoid TAO null handling issues. |
| `lead_ads_follow_up_event`  enum{whatsapp\_conversations} | The selected lead follow-up event for lead ads campaigns. |
| `lead_ads_quality_volume_setting`  enum{max\_volume, more\_volume, balanced, more\_quality, max\_quality} | The quality-vs-volume preference setting for lead ads campaigns. |
| `dataset_split_specs`  array<JSON object> | MTA / Seller Optimization dataset-split definitions (key: seller\_id or brand; value: the brand / vendor\_id to optimize for). |
| `key`  string | key  Required |
| `value`  string | value  Required |
| `omnichannel_object`  Object |  |
| `app`  array<JSON object> |  |
| `pixel`  array<JSON object> | Required |
| `onsite`  array<JSON object> |  |
| `whats_app_business_phone_number_id`  numeric string or integer |  |
| `whatsapp_phone_number`  string |  |
| `smart_promotion_type`  enum{GUIDED\_CREATION, SMART\_APP\_PROMOTION} | smart\_promotion\_type |
| `special_ad_category`  enum{NONE, EMPLOYMENT, HOUSING, CREDIT, ISSUES\_ELECTIONS\_POLITICS, ONLINE\_GAMBLING\_AND\_GAMING, FINANCIAL\_PRODUCTS\_SERVICES} | special\_ad\_category |
| `special_ad_category_country`  array<enum {AC, AD, AE, AF, AG, AI, AL, AM, AN, AO, AQ, AR, AS, AT, AU, AW, AX, AZ, BA, BB, BD, BE, BF, BG, BH, BI, BJ, BL, BM, BN, BO, BQ, BR, BS, BT, BV, BW, BY, BZ, CA, CC, CD, CF, CG, CH, CI, CK, CL, CM, CN, CO, CR, CU, CV, CW, CX, CY, CZ, DE, DJ, DK, DM, DO, DZ, EC, EE, EG, EH, ER, ES, ET, FI, FJ, FK, FM, FO, FR, GA, GB, GD, GE, GF, GG, GH, GI, GL, GM, GN, GP, GQ, GR, GS, GT, GU, GW, GY, HK, HM, HN, HR, HT, HU, ID, IE, IL, IM, IN, IO, IQ, IR, IS, IT, JE, JM, JO, JP, KE, KG, KH, KI, KM, KN, KP, KR, KW, KY, KZ, LA, LB, LC, LI, LK, LR, LS, LT, LU, LV, LY, MA, MC, MD, ME, MF, MG, MH, MK, ML, MM, MN, MO, MP, MQ, MR, MS, MT, MU, MV, MW, MX, MY, MZ, NA, NC, NE, NF, NG, NI, NL, NO, NP, NR, NU, NZ, OM, PA, PE, PF, PG, PH, PK, PL, PM, PN, PR, PS, PT, PW, PY, QA, RE, RO, RS, RU, RW, SA, SB, SC, SD, SE, SG, SH, SI, SJ, SK, SL, SM, SN, SO, SR, SS, ST, SV, SX, SY, SZ, TC, TD, TF, TG, TH, TJ, TK, TL, TM, TN, TO, TR, TT, TV, TW, TZ, UA, UG, UM, US, UY, UZ, VA, VC, VE, VG, VI, VN, VU, WF, WS, XK, YE, YT, ZA, ZM, ZW}> | special\_ad\_category\_country |
| `spend_cap`  int64 | A spend cap for the campaign, such that it will not spend more than this cap. Defined as integer value of subunit in your currency with a minimum value of $100 USD (or approximate local equivalent). Set the value to 922337203685478 to remove the spend cap. Not available for Reach and Frequency or Premium Self Serve campaigns |
| `start_time`  datetime | start\_time |
| `status`  enum{ACTIVE, PAUSED, DELETED, ARCHIVED} | Only `ACTIVE` and `PAUSED` are valid during creation. Other statuses can be used for update. If it is set to `PAUSED`, its active child objects will be paused and have an effective status `CAMPAIGN_PAUSED`. |
| `stop_time`  datetime | stop\_time |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 613 | Calls to this api have exceeded the rate limit. |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 190 | Invalid OAuth 2.0 Access Token |
| 801 | Invalid operation |

## Deleting

You can delete a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) by making a DELETE request to [`/{campaign_id}`](/docs/marketing-api/reference/ad-campaign-group/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |

You can dissociate a [Campaign](/docs/marketing-api/reference/ad-campaign-group/) from an [AdAccount](/docs/marketing-api/reference/ad-account/) by making a DELETE request to [`/act_{ad_account_id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `before_date`  datetime | Set a before date to delete campaigns before this date |
| `delete_strategy`  enum{DELETE\_ANY, DELETE\_OLDEST, DELETE\_ARCHIVED\_BEFORE} | Delete strategy  Required |
| `object_count`  integer | Object count |

### Return Type

Struct {

`objects_left_to_delete_count`: unsigned int32,

`deleted_object_ids`: List [

numeric string

],

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Objective Validation

These older objectives are deprecated with the release of [Marketing API v17.0](/docs/graph-api/changelog/version17.0#marketing-api). Please refer to the [Outcome-Driven Ads Experiences mapping table](#odax-mapping) below to find the new objectives and their corresponding destination types, optimization goals and promoted objects.

Your campaign objective choice can limit the settings available to you.

### Optimization Goals

Certain campaign objectives support only certain ad set `optimization_goals`. See [Bidding Overview, Validation](/docs/marketing-api/bidding/overview#opt-goal-validation).

### Compatible Ad Types

Objective | Compatible Ad Types || `APP_INSTALLS` | * Image Ads * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [App Ads](/docs/marketing-api/mobile-app-ads) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Ads](/docs/marketing-api/dynamic-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `BRAND_AWARENESS` | * Image Ads * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `CONVERSIONS` | * Image Ads * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Collection Ads](/docs/marketing-api/guides/collection) * [App Ads](/docs/marketing-api/mobile-app-ads) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Ads that click to Messenger](/docs/marketing-api/guides/messenger#destination) * [Offer Ads](/docs/marketing-api/guides/offer-ads) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Ads](/docs/marketing-api/dynamic-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `EVENT_RESPONSES` | * Image Ads * Video Ads * Carousel Ads * [Event and Local Ads](/docs/marketing-api/guides/event-ads) |
| `LEAD_GENERATION` | * Image Ads * Video Ads * Carousel Ads * [Lead Ads](/docs/marketing-api/guides/lead-ads) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `LINK_CLICKS` | * Image Ads * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Collection Ads](/docs/marketing-api/guides/collection) * [App Ads](/docs/marketing-api/mobile-app-ads) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Offer Ads](/docs/marketing-api/guides/offer-ads) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Ads](/docs/marketing-api/dynamic-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `MESSAGES` | * Image Ads * Video Ads * Carousel Ads * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Messenger Ads](/docs/marketing-api/guides/messenger#destination) |
| `POST_ENGAGEMENT` | * Image Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) |
| `PRODUCT_CATALOG_SALES` | * Image Ads * Carousel Ads * [Collection Ads](/docs/marketing-api/guides/collection) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Dynamic Ads](/docs/marketing-api/dynamic-ads) * [Collaborative Ads](/docs/marketing-api/collaborative-ads) |
| `REACH` | * Image Ads * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |
| `STORE_VISITS` | * Image Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Collection Ads](/docs/marketing-api/guides/collection) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Offer Ads](/docs/marketing-api/guides/offer-ads) |
| `VIDEO_VIEWS` | * Video Ads * Carousel Ads * [Instant Experience Ads](/docs/marketing-api/guides/instant-experiences) * [Instagram Ads](/docs/marketing-api/guides/instagramads) (see [placement limitations](/docs/marketing-api/guides/instagramads/get-started#campaign)) * [Segment Asset Customization Ads](/docs/marketing-api/dynamic-creative/segment-asset-customization) * [Placement Asset Customization Ads](/docs/marketing-api/dynamic-creative/placement-asset-customization) * [Multi-Language Ads](/docs/marketing-api/multi-language-ads) * [Dynamic Creative](/docs/marketing-api/dynamic-creative/overview) |

### Objectives and Creative Fields

See our [ads guide](https://www.facebook.com/business/ads-guide/) for a list of creatives supported per objective. In the API, the objective determines which [ad creatives](/docs/reference/ads-api/adcreative) are valid.

Objective | Creative Fields || `APP_INSTALLS` | `object_story_id` or `object_story_spec` |
| `CONVERSIONS` | `object_story_id` or `object_story_spec`   Notes:   * If you are creating link ads not connected to a page, use the following creative fields: `title`, `body`, `object_url`, and `image_file` or `image_hash`. * Creative cannot include link ads pointing to an app store. |
| `EVENT_RESPONSES` | `object_story_id` or `object_story_spec` |
| `LEAD_GENERATION` | `object_story_id` or `object_story_spec` |
| `LINK_CLICKS` | `object_story_id` or `object_story_spec`   Notes:   * Creative cannot include link ads pointing to an app store. * If you select `LINK_CLICKS` as both optimization goal and billing event, you must include `call_to_action`. |
| `MESSAGES` | `object_story_spec` |
| `PAGE_LIKES` | `object_story_id`, `object_story_spec`, `object_id`, and `body` |
| `POST_ENGAGEMENT` | `object_story_id` or `object_story_spec`   Note: Creative cannot include link ads pointing to an app store. |
| `VIDEO_VIEWS` | `object_story_id` or `object_story_spec` |

### Objectives and Tracking Specs

Tracking specs are applied by default based on the objective specified, please see the full list of defaults by objective [here](/docs/marketing-api/tracking-specs#default).

There are two important scenarios to take into account:

* Tracking pixels are not applied by default, and you must specify it explicitly when your objective is `CONVERSIONS`.
* Mobile app ads will no longer track installs or app events by default. **You must explicitly specify to track installs or app events for mobile app ads otherwise your ad will not track.**

To specify to track an install or app event, set the following in your [ad](/docs/reference/ads-api/adgroup):

```
tracking_specs=[{'action.type':['mobile_app_install'],'application':[{your_app_id}]},{'action.type':['app_custom_event'],'application':[{your_app_id}]}]
```

### Objective and Promoted Objects

Certain objectives require the `promoted_object` to be set in ad sets. See [Promoted Object](/docs/marketing-api/reference/ad-promoted-object) for more information.

Objective | Required promoted\_object Fields || `APP_INSTALLS` | * `application_id` and `object_store_url` * If `optimization_goal` is `OFFSITE_CONVERSIONS`: `application_id`, `object_store_url`, and `custom_event_type` |
| `CONVERSIONS` | * `pixel_id` (Conversion pixel ID) * `pixel_id` (Facebook pixel ID) and `custom_event_type` * `pixel_id` (Facebook pixel ID), `pixel_rule`, and `custom_event_type` * `event_id` (Facebook event ID) and `custom_event_type` * For mobile app events: `application_id`, `object_store_url`, and `custom_event_type` * For offline conversions: `offline_conversion_data_set_id` (Offline dataset ID), and `custom_event_type` |
| `LINK_CLICKS` | For mobile app or Instant Experiences app engagement link clicks: `application_id` and `object_store_url`. |
| `PRODUCT_CATALOG_SALES` | * `product_set_id`, or * `product_set_id` and `custom_event_type` |
| `PAGE_LIKES` | `page_id` |
| `OFFER_CLAIMS` | `page_id` |

### Objective and Placements

Certain types of ad [placements](/docs/reference/ads-api/targeting-specs/#placement) are valid only for specific objectives or creatives. See [Business Help Center, Available ad placements for marketing objectives](https://www.facebook.com/business/help/279271845888065?id=369787570424415).

The table below shows some placements and their compatible objectives or creatives. You can pick a combination of those compatible placements. Note that:

* With `LEAD_GENERATION`, `device_platforms: desktop` cannot be selected together with `publisher_platforms: instagram`.
* If your objective is website traffic, `story` for `facebook_positions` does not support `destination_type: messenger`.
* If your objective is website traffic, `story` for `messenger_positions` does not support `destination_type: messenger`.
* If your objective is website traffic, `ig_search` and `explore_home` for `instagram_positions` do not support `destination_type: whatsapp & messenger`.

Objective | Creative | Placement || `APP_INSTALLS`, promoting an Instant Experiences app | Desktop app ads | `device_platforms`: `desktop` |
| `APP_INSTALLS`, promoting a mobile app | Photo or video mobile app ads | `device_platforms`: `mobile`   `publisher_platforms`: `facebook`, `feed`, `instagram`, `audience_network`   `facebook_positions`: `feed`, `video_feeds`, `instant articles` and `story`   `audience_network_positions`: `classic`, `rewarded_video`   `messenger_positions`: `story` |
| `BRAND_AWARENESS` | all | `publisher_platforms`: `facebook`, `instagram`, `audience_network`.   `facebook_positions`: `feed`, `video_feeds`, `instream_video` and `story`, which is currently under limited availability   `instagram_positions`: `stream`   `audience_network_positions`: `classic`, `instream_video` |
| `CONVERSIONS` | Photo or video link ads from a page | We support `BRAND_AWARENESS`, `APP_INSTALL`, `POST_ENGAGEMENT`, `VIDEO_VIEWS`, `REACH`, `WEBSITE_CONVERSIONS`, and `TRAFFIC`. Also supported: `right_hand_column` and `story` for `facebook_positions` and `messenger_positions`: `messenger_home` and `story`.   `facebook_positions`: `story` only supports the objective `WEBSITE_CONVERSIONS`   `messenger_positions`: `story` only supports the objective `WEBSITE_CONVERSIONS`   Exception: `instream_video` is not supported for this objective. |
| `CONVERSIONS` | Link ads not connected to a page | `facebook_positions`: `right_hand_column` |
| `CONVERSIONS` (promoting mobile app) | Photo or video mobile app ads | `device_platforms`: `mobile`.   `facebook_positions`: `right_hand_column` and `story`. `story` as a `facebook_positions` for this objective does not support `destination_type`: `messenger`.   `messenger_positions`: `messenger_home`   `story` as a `messenger_positions` for this objective does not support `destination_type: messenger`. |
| `EVENT_RESPONSES` | Event ads | As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `EVENT_RESPONSES` | Page post ads | `publisher_platforms`: `facebook`.   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `LEAD_GENERATION` | Page post ads | `device_platforms`: `mobile`, `desktop`   `publisher_platforms`: `facebook`, `instagram`   `facebook_positions`: `feed` and `story`, which is in limited availability   instagram\_positions: stream   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `LINK_CLICKS` | Photo or video link ads from a page | All, including `right_hand_column` and `messenger_positions`: `messenger_home` and `story`. |
| `LINK_CLICKS` | Link ads not connected to a page | `facebook_positions`: `right_hand_column` |
| `LINK_CLICKS`, promoting an Instant Experiences app | Desktop app ads | `device_platforms`: `desktop`   `facebook_positions`: `right_hand_column` |
| `LINK_CLICKS`, promoting a mobile app | Photo or video mobile app ads | `device_platforms`: `mobile`, `facebook_positions`: `right_hand_column` |
| `PAGE_LIKES` | Video creatives | `publisher_platforms`: `facebook`   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `POST_ENGAGEMENT` | Page post ads with video or photo | `publisher_platforms`: `facebook`, `instagram`   `device_platforms`: `mobile`, `desktop`   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `POST_ENGAGEMENT` | Page post ads with text only | `publisher_platforms`: `facebook`, `instagram`   `device_platforms`: `mobile`, `desktop`   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `POST_ENGAGEMENT` | New campaign | `publisher_platforms`: `facebook`, `instagram`   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `PRODUCT_CATALOG_SALES` | dynamic ads | All, including `right_hand_column` for `facebook_positions`. |
| `REACH` | Reach ads | All except `right_hand_column` for `facebook_positions` as of 3.0.   Includes `messenger_positions`: `story` and `story` for `facebook_positions`. |
| `STORE_VISITS` | store visit ads | `publisher_platforms`: `facebook`   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |
| `VIDEO_VIEWS` | Video ads | `publisher_platforms`: `facebook`, `instagram`, `audience_network`.   Includes `story` for `facebook_positions` but not with the `optimation_goal` set to `TWO_SECOND_CONTINUOUS_VIDEO_VIEWS`.   As of 3.0, you cannot use `right_hand_column` for `facebook_positions` |

### Objective, Optimization Goal and `attribution_spec`

Use click-through and view-through attribution windows for [ad set](/docs/marketing-api/reference/ad-campaign#Creating) to track conversions then use for ads delivery optimization. This is different from the attribution window you use for ads reporting. With `attribution_spec`, select a combination of click-through or view-through windows of 1 day or 7 days. The combinations you can use depend on your ad set's `optimization_goal` and campaign's `objective`.

**Recommended Default `attribution_spec`**

You may not have provided `attribution_spec` when you created ads sets optimized for Value Optimization. This is an optimization available for conversions, app installs, and product catalog sales objectives. In the past, we defaulted to a 1-day click through attribution window.

Objective | Optimization Goal | Allowed Combination || `CONVERSIONS, PRODUCT_CATALOG_SALES` | `OFFSITE_CONVERSIONS` | 1-day click   7-day click   1-day click and 1-day view   7-day click and 1-day view |
| `APP_INSTALLS, LINK_CLICKS` | `OFFSITE_CONVERSIONS` | 1-day click   7-day click |
| `APP_INSTALLS` | `APP_INSTALLS` | 1-day click   1-day click and 1-day engaged-view   1-day click and 1-day view   1-day click and 1-day engaged-view and 1-day view |
| `CONVERSIONS` | `INCREMENTAL_OFFSITE_ CONVERSIONS` | Null click, Null view |

For all other `optimization_goal` and `objective` combinations, you can only use 1-day click for `attribution_spec`.

### Outcome-Driven Ads Experiences Objective Validation

From v20.0 onwards, Impressions optimization goal is deprecated for the legacy Post Engagement objective and the `ON_POST` destination\_type.

#### Objective values

The following are newer objectives:

* `OUTCOME_APP_PROMOTION`
* `OUTCOME_AWARENESS`
* `OUTCOME_ENGAGEMENT`
* `OUTCOME_LEADS`
* `OUTCOME_SALES`
* `OUTCOME_TRAFFIC`

These newer objectives will eventually replace the original objectives `APP_INSTALLS`, `BRAND_AWARENESS`, `CONVERSIONS`, `EVENT_RESPONSES`, `LEAD_GENERATION`, `LINK_CLICKS`, `LOCAL_AWARENESS`, `MESSAGES`, `OFFER_CLAIMS`, `PAGE_LIKES`, `POST_ENGAGEMENT`, `PRODUCT_CATALOG_SALES`, `REACH`, `STORE_VISITS`, `VIDEO_VIEWS`. We will continue supporting these original objectives throughout 2022.

#### Limitations

* Trying to duplicate existing objective campaigns to use the new objective values (`OUTCOME_APP_PROMOTION`, `OUTCOME_AWARENESS`, `OUTCOME_ENGAGEMENT`, `OUTCOME_LEADS`, `OUTCOME_SALES`, `OUTCOME_TRAFFIC`) may throw an error.

#### Example

**Outcome-Driven Ads Experiences**

|  |  |
| --- | --- |
|  | ``` curl -X POST \     -F 'name="New ODAX Campaign"' \     -F 'objective="OUTCOME_ENGAGEMENT"' \     -F 'status="PAUSED"' \     -F 'special_ad_categories=[]' \     -F 'access_token=ACCESS_TOKEN \     https://graph.facebook.com/v11.0/   act_AD_ACCOUNT_ID/campaigns ``` |

**Legacy**

|  |  |
| --- | --- |
|  | ``` curl -X POST \   -F 'name="New Campaign"' \   -F 'objective="APP_INSTALLS"' \   -F 'status="PAUSED"' \   -F 'special_ad_categories=[]' \   -F 'access_token=ACCESS_TOKEN \   https://graph.facebook.com/v11.0/   act_AD_ACCOUNT_ID/campaigns ``` |

#### Objective Mapping

Old Objective | New Objective | Destination Type | Optimization Goal | Promoted Object || `BRAND_AWARENESS` | `OUTCOME_AWARENESS` | — | `AD_RECALL_LIFT` | `page_id` |
| `REACH` | `OUTCOME_AWARENESS` | — | `REACH` | `page_id` |
| `IMPRESSIONS` | `page_id` |
| `LINK_CLICKS` | `OUTCOME_TRAFFIC` | — | `LINK_CLICKS` | `application_id`, `object_store_url` |
| `LANDING_PAGE_VIEWS` | — |
| `REACH` | `application_id`, `object_store_url` |
| `IMPRESSIONS` | — |
| `MESSENGER` | `LINK_CLICKS` | — |
| `REACH` | — |
| `IMPRESSIONS` | — |
| `WHATSAPP` | `LINK_CLICKS` | `page_id` |
| `REACH` | `page_id` |
| `IMPRESSIONS` | `page_id` |
| `PHONE_CALL` | `QUALITY_CALL` | — |
| `LINK_CLICKS` | — |
| `POST_ENGAGEMENT` | `OUTCOME_ENGAGEMENT` | `ON_POST` | `POST_ENGAGEMENT` | — |
| `REACH` | — |
| `IMPRESSIONS` | — |
| `PAGE_LIKES` | `OUTCOME_ENGAGEMENT` | `ON_PAGE` | `PAGE_LIKES` | `page_id` |
| `EVENT_RESPONSES` | `OUTCOME_ENGAGEMENT` | `ON_EVENT` | `EVENT_RESPONSES` | — |
| `POST_ENGAGEMENT` | — |
| `REACH` | — |
| `IMPRESSIONS` | — |
| `APP_INSTALL` | `OUTCOME_APP_PROMOTION` | — | `LINK_CLICKS` | `application_id`, `object_store_url` |
| `OFFSITE_CONVERSIONS` | `application_id`, `object_store_url` |
| `APP_INSTALLS` | `application_id`, `object_store_url` |
| `VIDEO_VIEWS` | `OUTCOME_AWARENESS` | — | `THRUPLAY` | `page_id` |
| `TWO_SECOND_CONTINUOUS_VIDEO_VIEWS` | `page_id` |
| `OUTCOME_ENGAGEMENT` | `ON_VIDEO` | `THRUPLAY` | — |
| `TWO_SECOND_CONTINUOUS_VIDEO_VIEWS` | — |
| `LEAD_GENERATION` | `OUTCOME_LEADS` | `ON_AD` | `LEAD_GENERATION` | `page_id` |
| `QUALITY_LEAD` | `page_id` |
| `LEAD_FROM_MESSENGER` | `LEAD_GENERATION` | `page_id` |
| `LEAD_FROM_IG_DIRECT` | `LEAD_GENERATION` | `page_id` |
| `PHONE_CALL` | `QUALITY_CALL` | `page_id` |
| `MESSAGES` | `OUTCOME_ENGAGEMENT` | `MESSENGER` | `CONVERSATIONS` | `page_id` |
| `LINK_CLICKS` | `page_id` |
| `MESSENGER` | `LEAD_GENERATION` | `page_id` |
| `CONVERSIONS`  (See [Available conversion locations and events by objective in Meta Ads Manager](https://www.facebook.com/business/help/2035196646663270) for more information on available conversion events by objective.) | `OUTCOME_ENGAGEMENT` | — | `OFFSITE_CONVERSIONS` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `LINK_CLICKS` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `REACH` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `LANDING_PAGE_VIEWS` | `pixel_id`, `custom_event_type` |
| `IMPRESSIONS` | `pixel_id`, `custom_event_type` |
| `OUTCOME_LEADS` | — | `OFFSITE_CONVERSIONS` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `LINK_CLICKS` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `REACH` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `LANDING_PAGE_VIEWS` | `pixel_id`, `custom_event_type` |
| `IMPRESSIONS` | `pixel_id`, `custom_event_type` |
| `OUTCOME_SALES` | — | `OFFSITE_CONVERSIONS` | `pixel_id`, `custom_event_type` |
| `application_id`, `object_store_url` |
| `MESSENGER` | `CONVERSATIONS` | `page_id`, `pixel_id`, `custom_event_type` |
| `PHONE_CALL` | `QUALITY_CALL` | `page_id` |
| `PRODUCT_CATALOG_SALES` | `OUTCOME_SALES` | `WEBSITE` | `LINK_CLICKS` | Campaign: `product_catalog_id`  Ad set: `product_set_id`, `custom_event_type` |
| `STORE_VISITS` | `OUTCOME_AWARENESS` | — | `REACH` | `place_page_set_id` |
