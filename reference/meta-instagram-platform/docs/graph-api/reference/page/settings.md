Graph API Version

[v25.0](#)

# Page Settings

Settings such as privacy settings for a Facebook Page.

A Page Access Token is required for all methods.

## Reading

PageSettings

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fsettings&version=v25.0)

```
GET /v25.0/{page-id}/settings HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/settings',
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
    "/{page-id}/settings",
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
    "/{page-id}/settings",
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
                               initWithGraphPath:@"/{page-id}/settings"
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

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [PageSettings](/docs/graph-api/reference/page-settings/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `settings` edge from the following paths:

* [`/{page_id}/settings`](/docs/graph-api/reference/page/settings/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `option`  Object | Option is a JSON dictionary with a key for the setting and any arguments as values for that key. Keys listed as 'value-only' don't take extra options and can only be changed by passing true/false as a `value`. Note that only the first option is meaningful when changing a setting. Any later options will be dropped. If you want to change more than one setting, you must make more than one call |
| `PAGE_MODERATION_BLACKLIST`  string | Comma-separated list of words blacklisted from this Page. When updating, this must be passed as an `option` |
| `USERS_CAN_POST`  boolean | Value-only. If value is `true`, people can post to this Page's timeline |
| `REVIEW_POSTS_BY_OTHER`  boolean | Value-only. If value is `true`, posts by others are hidden by default. If `false`, posts are visible by default |
| `USERS_CAN_MESSAGE`  boolean | Value-only. If `true`, people can message this Page via a message button |
| `USERS_CAN_POST_PHOTOS`  boolean | Value-only. If value is `true`, people can post photos and videos to this Page |
| `USERS_CAN_TAG_PHOTOS`  boolean | Value-only. If value is `true`, people who like this page can tag people in photos posted by this Page |
| `WALL_COMBINED_POSTS`  boolean | Deprecated. Has no effect |
| `PLATFORM_OPTOUTS_CAN_POST`  boolean | Value-only. If value is `true`, prevent people who have turned off page management apps from posting to this Page |
| `SHOW_RECENT_POSTS_BY_OTHERS`  boolean | Value-only. If value is `true`, show recent posts by others |
| `APPEARS_IN_RELATED_PAGES`  boolean | Value-only. If value is `true`, suggest this Page in Related Pages |
| `SHOW_PARENT_POSTS_ON_LOCATIONS`  enum{Always show, Only show on location Pages that don't publish their own posts, Never show} | If the option is set to any valid values, show posts from this Page on location Pages based on this setting |
| `AGE_RESTRICTIONS`  enum{Public, People 17 and over, People 18 and over, People 19 and over, People 21 and over, People 24 and over, Alcohol-Related} | If the option is set to any valid values, restrict access to this Page based on the restriction |
| `PROFANITY_FILTER`  enum{Off, Medium, Strong} | If the option is set to any valid values, prevent profanity on this Page based on the level |
| `SHOW_LOCATIONS_TAB`  enum{Allow, Allow on mobile only, Don't allow} |  |
| `COUNTRY_RESTRICTIONS`  Object | Set option to a JSON-encoded object with any country restrictions included below |
| `restriction_type`  enum{blacklist, whitelist} | Type of restriction  Required |
| `countries`  list<enum{AF, AX, AL, DZ, AS, AD, AO, AI, AQ, AG, AR, AM, AW, AU, AT, AZ, BS, BH, BD, BB, BY, BE, BZ, BJ, BM, BT, BO, BQ, BA, BW, BV, BR, IO, BN, BG, BF, BI, CV, KH, CM, CA, KY, CF, TD, CL, CN, CX, CC, CO, KM, CG, CD, CK, CR, CI, HR, CU, CW, CY, CZ, DK, DG, DJ, DM, DO, EC, EG, SV, GQ, ER, EE, SZ, ET, FK, FO, FJ, FI, FR, GF, PF, TF, GA, GM, GE, DE, GH, GI, GR, GL, GD, GP, GU, GT, GG, GN, GW, GY, HT, HM, VA, HN, HK, HU, IS, IN, ID, IR, IQ, IE, IM, IL, IT, JM, JP, JE, JO, KZ, KE, KI, KP, KR, KW, KG, LA, LV, LB, LS, LR, LY, LI, LT, LU, MO, MK, MG, MW, MY, MV, ML, MT, MH, MQ, MR, MU, YT, MX, FM, MD, MC, MN, ME, MS, MA, MZ, MM, NA, NR, NP, NL, AN, NC, NZ, NI, NE, NG, NU, NF, MP, NO, OM, PK, PW, PS, PA, PG, PY, PE, PH, PN, PL, PT, PR, QA, RE, RO, RU, RW, BL, SH, KN, LC, MF, PM, VC, WS, SM, ST, SA, SN, RS, SC, SL, SG, SX, SK, SI, SB, SO, ZA, GS, SS, ES, LK, SD, SR, SJ, SE, CH, SY, TW, TJ, TZ, TH, TL, TG, TK, TO, TT, TN, TR, TM, TC, TV, UG, UA, AE, UK, GB, UM, US, UY, UZ, VU, VE, VN, VG, VI, WF, EH, YE, ZM, ZW}> | List of countries  Required |
| `AUTO_PUBLISH_PAGE_INFO_UPDATES`  boolean | Value-only. If value is `true`, Posts will be created when you update the Page buttons, description, phone number, address, business hours or website. |
| `IS_PUBLISHED`  boolean | Value-only. If value is `true`, it means that page is published. If value is `false`, page is unpublished. |
| `ALLOW_MARKETING_MESSAGE_SUBSCRIBER_GROWTH`  boolean |  |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
