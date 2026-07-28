Graph API Version

[v25.0](#)

# Archived Ad

An ad Facebook stores in the Ad Library. You can perform keyword searches or search by Page ID of ads stored in the Ad Library. See [Ad Library](https://www.facebook.com/ads/library) and [Ad Library API](/docs/marketing-api/reference/ads_archive/).

## Reading

An archived ad.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_ArchivedAd%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_ArchivedAd} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_ArchivedAd}',
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
    "...?fields={fieldname_of_type_ArchivedAd}",
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
    "...?fields={fieldname_of_type_ArchivedAd}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_ArchivedAd}"
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

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | The Library ID of the ad object. |
| `ad_creation_time`  string | The [UTC](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.timeanddate.com%2Ftime%2Faboututc.html&h=AUDrAme5cuSCVPi54P7LUU06p_FZMGdcxJcyFzMx39eiYC0EJt9TyNUCjfUQepmeNFvyDEiWGym6Z7IZC85PNAGc6kJKF2MDqru-QMV4fcQJ6IWX7DxEInuoaf5YxEmaP0uMZEamgJ9Nml8C) date and time when someone created the ad. This is not the same time as when the ad ran. Includes date and time separated by `T`. Example: `2019-01-24T19:02:04+0000`, where `+0000` is the UTC offset. |
| `ad_creative_bodies`  list<string> | A list of the text which displays in each unique ad card of the ad. Some ads run with multiple ad versions or carousel cards each with their own unique text. See [Reference, Ad Creative](https://developers.facebook.com/docs/marketing-api/reference/ad-creative/). |
| `ad_creative_link_captions`  list<string> | A list of the captions which appear in the call to action section for each unique ad card of the ad. Some ads run with multiple ad versions or carousel cards each with their own unique text that appears in the link. |
| `ad_creative_link_descriptions`  list<string> | A list of text descriptions which appear in the call to action section for each unique ad card of the ad. Some ads run with multiple ad versions or carousel cards each with their own unique text describing the link. |
| `ad_creative_link_titles`  list<string> | A list of titles which appear in the call to action section for each unique ad card of the ad. Some ads run with multiple ad versions or carousel cards each with their own unique title text about the link. |
| `ad_delivery_start_time`  string | Date and time when an advertiser wants to start delivering an ad. Provided in [UTC](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.timeanddate.com%2Ftime%2Faboututc.html&h=AUBxTGpeLeuKLTmgGm_hR16iFLbs06OncrwiLP5dTBKLsqq4dqZ1U0LS93kKfL3C5hpX0Mr3_KCu6jBHZ94EPNBfhexQ6ET_5JhPyMRTrGpJ6tiZWYT4SazTTM9fl_wKxM-gTEIrJYdl7qno) as in `ad_creation_time`.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `ad_delivery_stop_time`  string | The time when an advertiser wants to stop delivery of their ad. If this is blank, the ad will run until the advertiser stops it or they spend their entire campaign budget. In [UTC](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.timeanddate.com%2Ftime%2Faboututc.html&h=AUBcMtaIt85QrPM86QFM1JbGleNb8EeohFBbUA-RxFwkMPGfJvhL6avzT2lryZm_qwLQ-Nj1siY9LJ4F0T95iqiqqVElsPuRXb8dvKxqepGCUdpqlBYfXi2HNBshgFduw5RMvOpy5e4FlOi7).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `ad_snapshot_url`  string | String with URL link which displays the archived ad. This displays uncompressed images and videos from the ad. While you cannot currently download a batch of archived ads, you can download ad creative such as images and text for an individual ad. If you do so, it must be for analysis and you must comply with the data storage terms in our [Terms of Service](https://www.facebook.com/terms.php).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `age_country_gender_reach_breakdown`  [list<AgeCountryGenderReachBreakdown>](https://developers.facebook.com/docs/graph-api/reference/age-country-gender-reach-breakdown/) | The demographic distribution of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) in the UK & EU reached by the ad. **Available only for ads delivered to the UK & EU and POLITICAL\_AND\_ISSUE\_ADS delivered to Brazil** |
| `beneficiary_payers`  [list<BeneficiaryPayer>](https://developers.facebook.com/docs/graph-api/reference/beneficiary-payer/) | The reported beneficiaries and payers for this ad. **Available only for ads delivered to the EU** |
| `br_total_reach`  int32 | The estimated ad reach for Brazil. **Available for POLITICAL\_AND\_ISSUE\_ADS delivered to Brazil** |
| `bylines`  string | A string containing the name of the person, company, or entity that provided funding for the ad. Provided by the purchaser of the ad. **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `currency`  string | The currency used to pay for the ad, as an [ISO currency code](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.iso.org%2Fiso-4217-currency-codes.html&h=AUAlt0oAr4VnVr49ciSEQqwskXKGJlTMDqdilGezIeSO79l8Rdqiap_2Xwq0hdNeq3dhNlOMMNw74jBIiJbGtYewAA6z092L5sYdcdZVpOr6zZMuB5zk-sJEsPFSZuBcgkxnjPMHuI7jYT_k). **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `delivery_by_region`  [list<AudienceDistribution>](https://developers.facebook.com/docs/graph-api/reference/audience-distribution/) | Regional distribution of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad. Provided as a percentage and where regions are at a sub-country level. **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `demographic_distribution`  [list<AudienceDistribution>](https://developers.facebook.com/docs/graph-api/reference/audience-distribution/) | The demographic distribution of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad. Provided as age ranges and gender. Age ranges: Can be one of 18-24, 25-34, 35-44, 45-54, 55-64, 65+. Gender: Can be the following strings: "Male", "Female", "Unknown". **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `estimated_audience_size`  [InsightsRangeValue](https://developers.facebook.com/docs/graph-api/reference/insights-range-value/) | Estimated Audience Size generally estimates how many [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) meet the targeting and ad placement criteria that advertisers select while creating an ad. [Learn more](https://www.facebook.com/business/help/1665333080167380?id=176276233019487). **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `eu_total_reach`  int32 | The estimated combined ad reach for all locations inside the European Union. **Available only for ads delivered to the EU** |
| `impressions`  [InsightsRangeValue](https://developers.facebook.com/docs/graph-api/reference/insights-range-value/) | A string containing the number of times the ad created an impression. In ranges of: <1000, 1K-5K, 5K-10K, 10K-50K, 50K-100K, 100K-200K, 200K-500K, >1M. **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `languages`  list<string> | The list of languages contained within the ad. These are displayed in [ISO 639-1 language codes](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.iso.org%2Fstandard%2F22109.html&h=AUDVGyQAriGXLjI5m5Xykx-QSXnPEVb9TlVX6L5fB0Sn_MUGGWdit-Z_WD0b6OWWawkk4zmRg7KMW0V00MAXnn_8rKk0M49z0n9PVtbWiwRb0_s_6dVbZmQJ1BlgbQyxzGBnM5d1AH3whAiY). |
| `page_id`  numeric string | ID of the Facebook Page that ran the ad.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `page_name`  string | Name of the Facebook Page which ran the ad. |
| `publisher_platforms`  list<enum> | A list of Meta technologies where the archived ad appeared, such as Facebook or Instagram. |
| `spend`  [InsightsRangeValue](https://developers.facebook.com/docs/graph-api/reference/insights-range-value/) | A string showing the amount of money spent running the ad, as specified in `currency`. This is reported in ranges: <100, 100-499, 500-999, 1K-5K, 5K-10K, 10K- 50K, 50K-100K, 100K-200K, 200K-500K, >1M. **Available only for POLITICAL\_AND\_ISSUE\_ADS** |
| `target_ages`  list<numeric string> | The age ranges selected for ad targeting in the UK & EU. The lowest age that can be returned is 13; the highest is 65+. **Available only for ads delivered to the UK & EU and POLITICAL\_AND\_ISSUE\_ADS delivered to Brazil** |
| `target_gender`  enum | The genders selected for ad targeting in the UK & EU. Possible values: “Women”, “Men” or “All”. **Available only for ads delivered to the UK & EU and POLITICAL\_AND\_ISSUE\_ADS delivered to Brazil** |
| `target_locations`  [list<TargetLocation>](https://developers.facebook.com/docs/graph-api/reference/target-location/) | The locations included or excluded for ad targeting in the UK & EU. **Available only for ads delivered to the UK & EU and POLITICAL\_AND\_ISSUE\_ADS delivered to Brazil** |
| `total_reach_by_location`  list<KeyValue:string,int32> | The estimated combined ad reach broken down by location. Currently supported locations: EU, BR, and UK. |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
