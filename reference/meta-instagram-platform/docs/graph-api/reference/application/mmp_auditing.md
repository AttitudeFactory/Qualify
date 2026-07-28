Graph API Version

[v25.0](#)

# Application Mmp Auditing

## Reading

You can't perform this operation on this endpoint.

## Creating

You can't perform this operation on this endpoint.

## Updating

You can update an [Application](/docs/graph-api/reference/application/) by making a POST request to [`/{application_id}/mmp_auditing`](/docs/graph-api/reference/application/mmp_auditing/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `advertiser_id`  string | Apple's Identifier for Advertisers (IDFA) or Android's Advertising ID. You can see how Facebook fetches this on [iOS](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-ios-sdk%2Fblob%2F7fe08877ea773dc35a5e4d6d9d305fae57c513b6%2Fsrc%2FCore%2FFBUtility.m%23L334-L357&h=AUAtegTrdtsbIb8yuy-ykWdWuztDjF7Sgmj0FhHroV9gUglZgeEZcFcyV95fXCNr4AIZgPmAlwRRhhVOCOQzp9AHSBrteI129EHB0bibf9SRN2lyaqJTlSr750u5sh4SEvqVaRGw038cUK8N) or on [Android](/docs/reference/ads-api/mobile-conversions-endpoint/v2.2#android) |
| `attribution`  string | mobile\_cookie from the person's device. Use this only on Android or iOS devices before iOS 6. The format for this should be like `DDDECD0A-C076-4050-8CE8-C20EC3FC2BD3` |
| `attribution_method`  string | The attribution method used. The options are: {ARD, DEEPLINK, GPIR, MIR, SRN} |
| `attribution_model`  string | The attribution model that the client selected to be respected by MMP |
| `attribution_referrer`  string | The attribution referrer, if one was used |
| `auditing_token`  string | The token provided in claim response sent to MMP |
| `click_attr_window`  int64 | Time window of click attribution |
| `custom_events`  list<CustomEvent> | When the event\_type is custom\_app\_events, custom\_events should contain the names of the custom events. |
| `_eventName`  RegexParam | Event name, must match the regular expression /^[0-9a-zA-Z\_][0-9a-zA-Z \_-]{0,39}$/  Required |
| `_eventName_md5`  RegexParam | MD5 hash of the event name, must match the regular expression /^[A-Fa-f0-9]{32}$/ |
| `_valueToSum`  float | Values to Sum |
| `_logTime`  int64 | Time to Log |
| `_implicitlyLogged`  int64 | Whether this is implicitly logged |
| `_isTimedEvent`  boolean | Whether this is a timed event |
| `_session_id`  string |  |
| `_app_user_id`  string |  |
| `decline_reason`  string | The reason that the MMP rejected Meta's claim |
| `device_os`  string | The OS of the device the event was on |
| `engagement_type`  string | The engagement type from Meta's claim, such as engaged\_view |
| `event`  string | Event type that Facebook claimed for  Required |
| `event_id`  string | An MMP-defined event ID, unique for each event |
| `event_reported_time`  int64 | The time at which the event was reported to MMP |
| `fb_ad_id`  int64 | FBID of the ad in Meta's claim |
| `fb_adgroup_id`  int64 | FBID of the adgroup. Provide this parameter when the attribution method is ARD (auto-redirect). |
| `fb_click_time`  int64 | Ad click time in Meta claim |
| `fb_view_time`  int64 | Ad view time in Meta claim |
| `google_install_referrer`  string | The raw GPIR referrer string, if this event was attributed by GPIR |
| `inactivity_window_hours`  int64 | Inactivity window in hours |
| `install_id`  string | If this is an install event, install\_id should be an MMP-generated ID unique across all installs (which can be the same as the event\_id). If this is a post-install event, the install\_id should be MMP-defined install\_id of the install event that preceded this event. |
| `is_fb`  boolean | Result (whether the MMP attributed the event to Meta ads)  Required |
| `meta_install_referrer`  string | The raw MIR referrer string, if this event was attributed by MIR |
| `used_install_referrer`  boolean | Identifies whether MMP used the install referrer |
| `view_attr_window`  int64 | Time window of view attribution |

### Return Type

Struct {

`success`: bool,

} Or Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Deleting

You can't perform this operation on this endpoint.
