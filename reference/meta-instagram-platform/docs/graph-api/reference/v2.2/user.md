Graph API Version

[v25.0](#)

# User

Represents a Facebook user.

## Reading

Get fields and edges on a User.

### Requirements

Type | Description || [Access Tokens](/docs/facebook-login/guides/access-tokens) | [User](/docs/facebook-login/access-tokens#usertokens) |
| [Permissions](/docs/permissions/reference) | [public\_profile](/docs/permissions/reference/public_profile) |

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bperson-id%7D%2F&version=v25.0)

```
GET /v25.0/{person-id}/ HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{person-id}/',
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
    "/{person-id}/",
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
    "/{person-id}/",
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
                               initWithGraphPath:@"/{person-id}/"
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
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{person-id}/
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Default Public Profile Fields

The [`public_profile`](/docs/permissions/reference/public_profile) permission allows apps to read the following fields:

* `id`
* `first_name`
* `last_name`
* `middle_name`
* `name`
* `name_format`
* `picture`
* `short_name`

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | The app user's App-Scoped User ID. This ID is unique to the app and cannot be used by other apps.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `about`  string | *Returns no data as of April 4, 2018.* |
| `age_range`  [AgeRange](https://developers.facebook.com/docs/graph-api/reference/age-range/) | The age segment for this person expressed as a minimum and maximum age. For example, more than 18, less than 21.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `birthday`  string | The person's birthday. This is a fixed format string, like `MM/DD/YYYY`. However, people can control who can see the year they were born separately from the month and day so this string can be only the year (YYYY) or the month + day (MM/DD)  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `client_business_id`  numeric string | The client's Business ID associated with a Business Integration System User. |
| `education`  [list<EducationExperience>](https://developers.facebook.com/docs/graph-api/reference/education-experience/) | *Returns no data as of April 4, 2018.* |
| `email`  string | The User's primary email address listed on their profile. This field will not be returned if no valid email address is available.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `favorite_athletes`  [list<Experience>](https://developers.facebook.com/docs/graph-api/reference/experience/) | Athletes the User likes. |
| `favorite_teams`  [list<Experience>](https://developers.facebook.com/docs/graph-api/reference/experience/) | Sports teams the User likes. |
| `first_name`  string | The person's first name  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `gender`  string | The gender selected by this person, `male` or `female`. If the gender is set to a custom value, this value will be based off of the selected pronoun; it will be omitted if the pronoun is neutral.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `hometown`  [Page](https://developers.facebook.com/docs/graph-api/reference/page/) | The person's hometown |
| `inspirational_people`  [list<Experience>](https://developers.facebook.com/docs/graph-api/reference/experience/) | The person's inspirational people |
| `installed`  bool | Is the app making the request installed |
| `is_guest_user`  bool | if the current user is a guest user. should always return false. |
| `languages`  [list<Experience>](https://developers.facebook.com/docs/graph-api/reference/experience/) | Facebook Pages representing the languages this person knows |
| `last_name`  string | The person's last name  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `link`  string | A link to the person's Timeline. The link will only resolve if the person clicking the link is logged into Facebook and is a friend of the person whose profile is being viewed.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `local_news_megaphone_dismiss_status`  bool | Display megaphone for local news bookmark  Deprecated |
| `local_news_subscription_status`  bool | Daily local news notification  Deprecated |
| `locale`  string | The person's locale  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended)Deprecated |
| `location`  [Page](https://developers.facebook.com/docs/graph-api/reference/page/) | The person's current location as entered by them on their profile. This field requires the `user_location` permission.  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `meeting_for`  list<string> | What the person is interested in meeting for |
| `middle_name`  string | The person's middle name  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| `name`  string | The person's full name  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended)[Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name_format`  string | The person's name formatted to correctly handle Chinese, Japanese, or Korean ordering |
| `political`  string | *Returns no data as of April 4, 2018.* |
| `quotes`  string | The person's favorite quotes |
| `relationship_status`  string | *Returns no data as of April 4, 2018.* |
| `religion`  string | *Returns no data as of April 4, 2018.* |
| `shared_login_upgrade_required_by`  timestamp | The time that the shared login needs to be upgraded to Business Manager by |
| `significant_other`  [User](https://developers.facebook.com/docs/graph-api/reference/user/) | The person's significant other |
| `sports`  [list<Experience>](https://developers.facebook.com/docs/graph-api/reference/experience/) | Sports played by the person |
| `supports_donate_button_in_live_video`  bool | Whether the user can add a Donate Button to their Live Videos |
| `third_party_id`  string | A string containing an anonymous, unique identifier for the User, for use with third-parties. Deprecated for versions 3.0+. Apps using older versions of the API can get this field until January 8, 2019. Apps installed by the User on or after May 1st, 2018, cannot get this field.  Deprecated |
| `timezone`  float (min: -24) (max: 24) | The person's current timezone offset from UTC  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended)Deprecated |
| `token_for_business`  string | A token that is the same across a business's apps. Access to this token requires that the person be logged into your app or have a role on your app. This token will change if the business owning the app changes |
| `updated_time`  datetime | Updated time  Deprecated |
| `verified`  bool | Indicates whether the account has been verified. This is distinct from the `is_verified` field. Someone is considered verified if they take any of the following actions:   ```                                                                                                                                                                     * Register for mobile                                                                                                                                                                     * Confirm their account via SMS                                                                                                                                                                     * Enter a valid credit card ```  Deprecated |
| `video_upload_limits`  [VideoUploadLimits](https://developers.facebook.com/docs/graph-api/reference/video-upload-limits/) | Video upload limits |
| `website`  string | *Returns no data as of April 4, 2018.* |

### Edges

| Edge | Description |
| --- | --- |
| [`accounts`](/docs/graph-api/reference/user/accounts/)  Edge<Page> | Pages the User has a role on. |
| [`ad_studies`](/docs/graph-api/reference/user/ad_studies/)  Edge<AdStudy> | Ad studies that this User's can view. |
| [`albums`](/docs/graph-api/reference/user/albums/)  Edge<Album> | The photo albums this person has created |
| [`apprequestformerrecipients`](/docs/graph-api/reference/user/apprequestformerrecipients/)  Edge<AppRequestFormerRecipient> | App requests |
| [`apprequests`](/docs/graph-api/reference/user/apprequests/)  Edge<AppRequest> | This person's pending requests from an app  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| [`assigned_applications`](/docs/graph-api/reference/user/assigned_applications/)  Edge<Application> | assigned\_applications |
| [`assigned_business_asset_groups`](/docs/graph-api/reference/user/assigned_business_asset_groups/)  Edge<BusinessAssetGroup> | Business asset groups that are assign to this business scoped user |
| [`assigned_pages`](/docs/graph-api/reference/user/assigned_pages/)  Edge<Page> | Pages that are assigned to this business scoped user |
| [`assigned_product_catalogs`](/docs/graph-api/reference/user/assigned_product_catalogs/)  Edge<ProductCatalog> | Product catalogs that are assigned to this business scoped user |
| [`assigned_whatsapp_business_accounts`](/docs/graph-api/reference/user/assigned_whatsapp_business_accounts/)  Edge<WhatsAppBusinessAccount> | WhatsApp business accounts that are assigned to the business user |
| [`business_users`](/docs/graph-api/reference/user/business_users/)  Edge<BusinessUser> | Business users corresponding to the user |
| [`businesses`](/docs/graph-api/reference/user/businesses/)  Edge<Business> | Businesses associated with the user |
| [`conversations`](/docs/graph-api/reference/user/conversations/)  Edge<UnifiedThread> | Facebook Messenger conversation |
| [`custom_labels`](/docs/graph-api/reference/user/custom_labels/)  Edge<PageUserMessageThreadLabel> | custom\_labels |
| [`feed`](/docs/graph-api/reference/user/feed/)  Edge<Post> | The posts and links published by this person or others on their profile |
| [`ids_for_apps`](/docs/graph-api/reference/user/ids_for_apps/)  Edge<UserIDForApp> | Businesses can claim ownership of multiple apps using Business Manager. This edge returns the list of IDs that this user has in any of those other apps |
| [`ids_for_business`](/docs/graph-api/reference/user/ids_for_business/)  Edge<UserIDForApp> | Businesses can claim ownership of multiple apps using Business Manager. This edge returns the list of IDs that this user has in any of those other apps |
| [`ids_for_pages`](/docs/graph-api/reference/user/ids_for_pages/)  Edge<UserIDForPage> | Businesses can claim ownership of apps and pages using Business Manager. This edge returns the list of IDs that this user has in any of the pages owned by this business |
| [`likes`](/docs/graph-api/reference/user/likes/)  Edge<Page> | All the Pages this person has liked |
| [`live_videos`](/docs/graph-api/reference/user/live_videos/)  Edge<LiveVideo> | Live videos from this person |
| [`music`](/docs/graph-api/reference/user/music/)  Edge<Page> | Music this person likes |
| [`payment.subscriptions`](/docs/graph-api/reference/user/payment.subscriptions/)  Edge<PaymentSubscription> | Payment subscriptions |
| [`permissions`](/docs/graph-api/reference/user/permissions/)  Edge<Permission> | The permissions that the person has granted this app  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| [`photos`](/docs/graph-api/reference/user/photos/)  Edge<Photo> | Photos the person is tagged in or has uploaded |
| [`picture`](/docs/graph-api/reference/user/picture/)  Edge<ProfilePictureSource> | The person's profile picture  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended) |
| [`rich_media_documents`](/docs/graph-api/reference/user/rich_media_documents/)  Edge<Canvas> | A list of rich media documents belonging to Pages that the user has advertiser permissions on |
| [`videos`](/docs/graph-api/reference/user/videos/)  Edge<Video> | Videos the person is tagged in or uploaded |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80006 | There have been too many messenger api calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 104 | Incorrect signature |
| 459 | The session is invalid because the user has been checkpointed |
| 613 | Calls to this api have exceeded the rate limit. |
| 200 | Permissions error |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 80002 | There have been too many calls to this Instagram account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can update a [User](/docs/graph-api/reference/user/) by making a POST request to [`/{user_id}`](/docs/graph-api/reference/user/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `emoji_color_pref`  int64 | emoji color preference. |
| `firstname`  string | This person's first name |
| `lastname`  string | This person's last name |
| `local_news_megaphone_dismiss_status`  enum {YES, NO} | Dismisses local news megaphone |
| `local_news_subscription_status`  enum {STATUS\_ON, STATUS\_OFF} | Preference for setting local news notifications |
| `name`  string | Used for test accounts only. Name for this account |
| `password`  string | Used for test accounts only. Password for this account |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 190 | Invalid OAuth 2.0 Access Token |
| 459 | The session is invalid because the user has been checkpointed |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |
| 102 | Session key invalid or no longer valid |
| 100 | Invalid parameter |
| 240 | Desktop applications cannot call this function for other users |
| 483 | The session is invalid because the user is in consent app blocking |
| 2500 | Error parsing graph query |

You can update a [User](/docs/graph-api/reference/user/) by making a POST request to [`/{custom_audience_id}/users`](/docs/marketing-api/reference/custom-audience/users/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=POST&path=%3CCUSTOM_AUDIENCE_ID%3E%2Fusers%3Fpayload%3D%257B%2522schema%2522%253A%255B%2522EMAIL%2522%252C%2522LOOKALIKE_VALUE%2522%255D%252C%2522data%2522%253A%255B%255B%25229b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254%2522%252C44.5%255D%252C%255B%25228cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee%2522%252C140%255D%252C%255B%25224eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a%2522%252C0%255D%252C%255B%252298df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56%2522%252C0.9%255D%255D%257D&version=v25.0)

```
POST /v25.0/<CUSTOM_AUDIENCE_ID>/users HTTP/1.1
Host: graph.facebook.com

payload=%7B%22schema%22%3A%5B%22EMAIL%22%2C%22LOOKALIKE_VALUE%22%5D%2C%22data%22%3A%5B%5B%229b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254%22%2C44.5%5D%2C%5B%228cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee%22%2C140%5D%2C%5B%224eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a%22%2C0%5D%2C%5B%2298df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56%22%2C0.9%5D%5D%7D
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/<CUSTOM_AUDIENCE_ID>/users',
    array (
      'payload' => '{"schema":["EMAIL","LOOKALIKE_VALUE"],"data":[["9b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254",44.5],["8cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee",140],["4eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a",0],["98df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56",0.9]]}',
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
    "/<CUSTOM_AUDIENCE_ID>/users",
    "POST",
    {
        "payload": "{\"schema\":[\"EMAIL\",\"LOOKALIKE_VALUE\"],\"data\":[[\"9b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254\",44.5],[\"8cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee\",140],[\"4eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a\",0],[\"98df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56\",0.9]]}"
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
params.putString("payload", "{\"schema\":[\"EMAIL\",\"LOOKALIKE_VALUE\"],\"data\":[[\"9b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254\",44.5],[\"8cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee\",140],[\"4eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a\",0],[\"98df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56\",0.9]]}");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/<CUSTOM_AUDIENCE_ID>/users",
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
  @"payload": @"{\"schema\":[\"EMAIL\",\"LOOKALIKE_VALUE\"],\"data\":[[\"9b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254\",44.5],[\"8cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee\",140],[\"4eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a\",0],[\"98df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56\",0.9]]}",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/<CUSTOM_AUDIENCE_ID>/users"
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
  -F 'payload={
       "schema": [
         "EMAIL",
         "LOOKALIKE_VALUE"
       ],
       "data": [
         [
           "9b431636bd164765d63c573c346708846af4f68fe3701a77a3bdd7e7e5166254",
           44.5
         ],
         [
           "8cc62c145cd0c6dc444168eaeb1b61b351f9b1809a579cc9b4c9e9d7213a39ee",
           140
         ],
         [
           "4eaf70b1f7a797962b9d2a533f122c8039012b31e0a52b34a426729319cb792a",
           0
         ],
         [
           "98df8d46f118f8bef552b0ec0a3d729466a912577830212a844b73960777ac56",
           0.9
         ]
       ]
     }' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/<CUSTOM_AUDIENCE_ID>/users
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `payload`  Object | Payload representing users to add |
| `schema`  string | `EMAIL_SHA256`, `PHONE_SHA256`, `MOBILE_ADVERTISER_ID`. One can also pass an array of multiple keys for multi-key match. Supported key types includes:   `EXTERN_ID` `EMAIL` `PHONE` `GEN` `DOBY` `DOBM` `DOBD` `LN` `FN` `FI` `CT` `ST` `ZIP` `MADID` `COUNTRY` The multi-key array is of the form `["EMAIL", "LN", "FN", "ZIP"]` |
| `is_raw`  boolean | Is the key raw? If the keys are combinational keys like "LN\_FN\_ZIP", set this to `false`, otherwise set this to `true`. Default to false |
| `data`  list<JSON array> | Array with users data. If the multi-key feature is used, a two-dimensional array of the form `[["<HASHED_EMAIL>", "<HASHED_FN>", "<HASHED_LN>", "<HASHED_ZIP>"], ["", "<HASHED_FN>", "<HASHED_LN>", "<HASHED_ZIP>"]]` should be passed.In case a key is unknown, it should be left blank. |
| `app_ids`  list<int> | App ids used by the users being uploaded. This field is required when `schema` is a Facebook UID and the IDs were collected by an App integration. e.g. `[1234,5678]` |
| `page_ids`  list<Page ID> | Page ids used by the users being uploaded. This field is required when `schema` is a Facebook UID and the IDs were collected by a Page webhook integration. e.g. `[1234,5678]` |
| `ig_account_ids`  list<numeric string or integer> |  |
| `data_source`  Object | Indicates by which method the custom audience was created, defined by the `type` and `subtype` of the `data_source` |
| `type`  enum {UNKNOWN, FILE\_IMPORTED, EVENT\_BASED, SEED\_BASED, THIRD\_PARTY\_IMPORTED, COPY\_PASTE, CONTACT\_IMPORTER, HOUSEHOLD\_AUDIENCE} | Type of the custom audience |
| `sub_type`  enum {ANYTHING, NOTHING, HASHES, USER\_IDS, HASHES\_OR\_USER\_IDS, MOBILE\_ADVERTISER\_IDS, EXTERNAL\_IDS, MULTI\_HASHES, TOKENS, EXTERNAL\_IDS\_MIX, HOUSEHOLD\_EXPANSION, SUBSCRIBER\_LIST, WEB\_PIXEL\_HITS, MOBILE\_APP\_EVENTS, MOBILE\_APP\_COMBINATION\_EVENTS, VIDEO\_EVENTS, WEB\_PIXEL\_COMBINATION\_EVENTS, PLATFORM, MULTI\_DATA\_EVENTS, IG\_BUSINESS\_EVENTS, STORE\_VISIT\_EVENTS, INSTANT\_ARTICLE\_EVENTS, FB\_EVENT\_SIGNALS, FACEBOOK\_WIFI\_EVENTS, AR\_EXPERIENCE\_EVENTS, AR\_EFFECTS\_EVENTS, MESSENGER\_ONSITE\_SUBSCRIPTION, WHATSAPP\_SUBSCRIBER\_POOL, MARKETPLACE\_LISTINGS, AD\_CAMPAIGN, GROUP\_EVENTS, MESSAGE\_CAMPAIGN, ENGAGEMENT\_EVENT\_USERS, CUSTOM\_AUDIENCE\_USERS, PAGE\_FANS, CONVERSION\_PIXEL\_HITS, APP\_USERS, S\_EXPR, DYNAMIC\_RULE, CAMPAIGN\_CONVERSIONS, WEB\_PIXEL\_HITS\_CUSTOM\_AUDIENCE\_USERS, MOBILE\_APP\_CUSTOM\_AUDIENCE\_USERS, COMBINATION\_CUSTOM\_AUDIENCE\_USERS, VIDEO\_EVENT\_USERS, FB\_PIXEL\_HITS, IG\_PROMOTED\_POST, PLACE\_VISITS, OFFLINE\_EVENT\_USERS, EXPANDED\_AUDIENCE, SEED\_LIST, PARTNER\_CATEGORY\_USERS, PAGE\_SMART\_AUDIENCE, MULTICOUNTRY\_COMBINATION, PLATFORM\_USERS, MULTI\_EVENT\_SOURCE, SMART\_AUDIENCE, LOOKALIKE\_PLATFORM, SIGNAL\_SOURCE, MAIL\_CHIMP\_EMAIL\_HASHES, CONSTANT\_CONTACTS\_EMAIL\_HASHES, COPY\_PASTE\_EMAIL\_HASHES, CUSTOM\_DATA\_TARGETING, CONTACT\_IMPORTER, DATA\_FILE} | Subtype of the custom audience |
| `metadata`  Object |  |
| `calculated_date`  datetime |  |
| `schema_version`  string |  |
| `session`  Object | Information about the session. Sessions are used when you have a lot of users to upload. For example, if you have 1 million users to upload, you need to split them into at least 100 requests because each request can only take 10k users. Specify the session info so that you can track if the session has finished or not. |
| `session_id`  int64 | Advertiser generated session identifier, used to track the session. Needs to be unique in the same ad account. |
| `estimated_num_total`  int64 | Estimated total num of users to be uploaded in this session, used by Facebook systems to better process this session. |
| `batch_seq`  int64 | A 1 based sequence number to identify the request in the session. |
| `last_batch_flag`  boolean | `true` mean this request is the last request in this session. You must mark the last request otherwise Facebook doesn't know the session has ended |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`audience_id`: numeric string,

`session_id`: numeric string,

`num_received`: int32,

`num_invalid_entries`: int32,

`invalid_entry_samples`: Map {

string: string

},

`subscription_info`: Struct {

`whatsapp`: Struct {

`error`: Struct {

`message`: string,

`code`: int32,

},

`num_subscribers_received`: int32,

`num_subscribers_invalid_entries`: int32,

`invalid_subscribers_entry_samples`: Map {

string: string

},

},

`messenger`: Struct {

`error`: Struct {

`message`: string,

`code`: int32,

},

`num_subscribers_received`: int32,

`num_subscribers_invalid_entries`: int32,

`invalid_subscribers_entry_samples`: Map {

string: string

},

},

},

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 2650 | Failed to update the custom audience |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 105 | The number of parameters exceeded the maximum for this operation |
| 194 | Missing at least one required parameter |

## Deleting

Delete a test user

You can delete a [User](/docs/graph-api/reference/user/) by making a DELETE request to [`/{user_id}`](/docs/graph-api/reference/user/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 2903 | Cannot delete this test account |
| 2904 | Cannot delete the OG Test User |
| 100 | Invalid parameter |
| 240 | Desktop applications cannot call this function for other users |
| 102 | Session key invalid or no longer valid |
| 200 | Permissions error |

You can dissociate a [User](/docs/graph-api/reference/user/) from a [Page](/docs/graph-api/reference/page/) by making a DELETE request to [`/{page_id}/blocked`](/docs/graph-api/reference/page/blocked/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `asid`  user/page ID | App Scoped User ID to unblock |
| `psid`  UID | Page Scoped User ID to unblock |
| `uid`  UID | Deprecated. Same as `user` |
| `user`  UID | List of User or Page IDs to unblock. This or `uid` is required |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |

You can dissociate a [User](/docs/graph-api/reference/user/) from an [AdAccount](/docs/marketing-api/reference/ad-account/) by making a DELETE request to [`/act_{ad_account_id}/assigned_users`](/docs/marketing-api/reference/ad-account/assigned_users/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `user`  UID | Business user id or system user id  Required |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 3919 | There was an unexpected technical issue. Please try again. |
| 190 | Invalid OAuth 2.0 Access Token |

You can dissociate a [User](/docs/graph-api/reference/user/) from a [CustomAudience](/docs/marketing-api/reference/custom-audience/) by making a DELETE request to [`/{custom_audience_id}/users`](/docs/marketing-api/reference/custom-audience/users/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `payload`  Object | Payload representing users to delete |
| `schema`  string | `EMAIL_SHA256`, `PHONE_SHA256`, `MOBILE_ADVERTISER_ID`. One can also pass an array of multiple keys for multi-key match. Supported key types includes:   `EXTERN_ID` `EMAIL` `PHONE` `GEN` `DOBY` `DOBM` `DOBD` `LN` `FN` `FI` `CT` `ST` `ZIP` `MADID` `COUNTRY` The multi-key array is of the form `["EMAIL", "LN", "FN", "ZIP"]` |
| `is_raw`  boolean | Is the key raw? If the keys are combinational keys like "LN\_FN\_ZIP", set this to `false`, otherwise set this to `true`. Default to false |
| `data`  list<JSON array> | Array with users data. If the multi-key feature is used, a two-dimensional array of the form `[["<HASHED_EMAIL>", "<HASHED_FN>", "<HASHED_LN>", "<HASHED_ZIP>"], ["", "<HASHED_FN>", "<HASHED_LN>", "<HASHED_ZIP>"]]` should be passed.In case a key is unknown, it should be left blank. |
| `app_ids`  list<int> | App ids used by the users being uploaded. This field is required when `schema` is a Facebook UID and the IDs were collected by an App integration. e.g. `[1234,5678]` |
| `page_ids`  list<Page ID> | Page ids used by the users being uploaded. This field is required when `schema` is a Facebook UID and the IDs were collected by a Page webhook integration. e.g. `[1234,5678]` |
| `ig_account_ids`  list<numeric string or integer> |  |
| `data_source`  Object | Indicates by which method the custom audience was created, defined by the `type` and `subtype` of the `data_source` |
| `type`  enum {UNKNOWN, FILE\_IMPORTED, EVENT\_BASED, SEED\_BASED, THIRD\_PARTY\_IMPORTED, COPY\_PASTE, CONTACT\_IMPORTER, HOUSEHOLD\_AUDIENCE} | Type of the custom audience |
| `sub_type`  enum {ANYTHING, NOTHING, HASHES, USER\_IDS, HASHES\_OR\_USER\_IDS, MOBILE\_ADVERTISER\_IDS, EXTERNAL\_IDS, MULTI\_HASHES, TOKENS, EXTERNAL\_IDS\_MIX, HOUSEHOLD\_EXPANSION, SUBSCRIBER\_LIST, WEB\_PIXEL\_HITS, MOBILE\_APP\_EVENTS, MOBILE\_APP\_COMBINATION\_EVENTS, VIDEO\_EVENTS, WEB\_PIXEL\_COMBINATION\_EVENTS, PLATFORM, MULTI\_DATA\_EVENTS, IG\_BUSINESS\_EVENTS, STORE\_VISIT\_EVENTS, INSTANT\_ARTICLE\_EVENTS, FB\_EVENT\_SIGNALS, FACEBOOK\_WIFI\_EVENTS, AR\_EXPERIENCE\_EVENTS, AR\_EFFECTS\_EVENTS, MESSENGER\_ONSITE\_SUBSCRIPTION, WHATSAPP\_SUBSCRIBER\_POOL, MARKETPLACE\_LISTINGS, AD\_CAMPAIGN, GROUP\_EVENTS, MESSAGE\_CAMPAIGN, ENGAGEMENT\_EVENT\_USERS, CUSTOM\_AUDIENCE\_USERS, PAGE\_FANS, CONVERSION\_PIXEL\_HITS, APP\_USERS, S\_EXPR, DYNAMIC\_RULE, CAMPAIGN\_CONVERSIONS, WEB\_PIXEL\_HITS\_CUSTOM\_AUDIENCE\_USERS, MOBILE\_APP\_CUSTOM\_AUDIENCE\_USERS, COMBINATION\_CUSTOM\_AUDIENCE\_USERS, VIDEO\_EVENT\_USERS, FB\_PIXEL\_HITS, IG\_PROMOTED\_POST, PLACE\_VISITS, OFFLINE\_EVENT\_USERS, EXPANDED\_AUDIENCE, SEED\_LIST, PARTNER\_CATEGORY\_USERS, PAGE\_SMART\_AUDIENCE, MULTICOUNTRY\_COMBINATION, PLATFORM\_USERS, MULTI\_EVENT\_SOURCE, SMART\_AUDIENCE, LOOKALIKE\_PLATFORM, SIGNAL\_SOURCE, MAIL\_CHIMP\_EMAIL\_HASHES, CONSTANT\_CONTACTS\_EMAIL\_HASHES, COPY\_PASTE\_EMAIL\_HASHES, CUSTOM\_DATA\_TARGETING, CONTACT\_IMPORTER, DATA\_FILE} | Subtype of the custom audience |
| `metadata`  Object |  |
| `calculated_date`  datetime |  |
| `schema_version`  string |  |
| `session`  Object | Information about the session. Sessions are used when you have a lot of users to upload. For example, if you have 1 million users to upload, you need to split them into at least 100 requests because each request can only take 10k users. Specify the session info so that you can track if the session has finished or not. |
| `session_id`  int64 | Advertiser generated session identifier, used to track the session. Needs to be unique in the same ad account. |
| `estimated_num_total`  int64 | Estimated total num of users to be uploaded in this session, used by Facebook systems to better process this session. |
| `batch_seq`  int64 | A 1 based sequence number to identify the request in the session. |
| `last_batch_flag`  boolean | `true` mean this request is the last request in this session. You must mark the last request otherwise Facebook doesn't know the session has ended |

### Return Type

Struct {

`audience_id`: numeric string,

`session_id`: numeric string,

`num_received`: int32,

`num_invalid_entries`: int32,

`invalid_entry_samples`: Map {

string: string

},

`subscription_info`: Struct {

`whatsapp`: Struct {

`error`: Struct {

`message`: string,

`code`: int32,

},

`num_subscribers_received`: int32,

`num_subscribers_invalid_entries`: int32,

`invalid_subscribers_entry_samples`: Map {

string: string

},

},

`messenger`: Struct {

`error`: Struct {

`message`: string,

`code`: int32,

},

`num_subscribers_received`: int32,

`num_subscribers_invalid_entries`: int32,

`invalid_subscribers_entry_samples`: Map {

string: string

},

},

},

}

### Error Codes

| Error | Description |
| --- | --- |
| 80003 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#custom-audience. |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 2650 | Failed to update the custom audience |
| 190 | Invalid OAuth 2.0 Access Token |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
