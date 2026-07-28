Graph API Version

[v25.0](#)

# Page Subscribed Apps

[Webhook](/docs/graph-api/webhooks/getting-started/webhooks-for-pages) subscriptions for apps that service a Facebook Page.

It is possible to subscribe to more fields at the page level than the app level. However, only fields with subscriptions at both the page and app levels will get Webhooks. To make sure you are subscribed to the same fields at the app level, [use the app subscriptions endpoint](/docs/graph-api/reference/v12.0/app/subscriptions).

## Reading

Get the [Webhooks](/docs/graph-api/webhooks/getting-started/webhooks-for-pages) an app is subscribed to for a Facebook Page.

### Permissions

* A Page access token requested by a person who can perform the

  [`CREATE_CONTENT`,](#)

  [`MANAGE`, or](#)

  [`MODERATE`](#)

  on the Page being queried
* The `pages_manage_metadata` permission
* The `pages_show_list` permission

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fsubscribed_apps&version=v25.0)

```
GET /v25.0/{page-id}/subscribed_apps HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/subscribed_apps',
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
    "/{page-id}/subscribed_apps",
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
    "/{page-id}/subscribed_apps",
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
                               initWithGraphPath:@"/{page-id}/subscribed_apps"
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

A list of [Application](/docs/graph-api/reference/application/) nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `subscribed_fields`  list<enum> | Webhook fields to which the app has subscribed on the page  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 210 | User not visible |
| 100 | Invalid parameter |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 104 | Incorrect signature |

## Creating

Subscribe your app to a [Webhook](/docs/graph-api/webhooks/getting-started/webhooks-for-pages) for a Facebook Page.

### Permissions

* A Page access token requested by a person who can perform

  [`CREATE_CONTENT`,](#)

  [`MANAGE`, or](#)

  [`MODERATE`](#)

  task on the Page
* The `pages_manage_metadata` permission
* The `pages_show_list` permission

**Note:** You cannot use the `subscribed_fields` parameter to configure or subscribe to [Webhooks for Instagram](/docs/graph-api/webhooks/getting-started/webhooks-for-instagram). You must use your app dashboard to subscribe to Instagram Webhooks.

You can make a POST request to `subscribed_apps` edge from the following paths:

* [`/{page_id}/subscribed_apps`](/docs/graph-api/reference/page/subscribed_apps/)

When posting to this edge, a [Page](/docs/graph-api/reference/page/) will be created.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=POST&path=%7Bpage-id%7D%2Fsubscribed_apps%3Fsubscribed_fields%3Dleadgen&version=v25.0)

```
POST /v25.0/{page-id}/subscribed_apps HTTP/1.1
Host: graph.facebook.com

subscribed_fields=leadgen
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{page-id}/subscribed_apps',
    array (
      'subscribed_fields' => 'leadgen',
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
    "/{page-id}/subscribed_apps",
    "POST",
    {
        "subscribed_fields": "leadgen"
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
params.putString("subscribed_fields", "leadgen");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/subscribed_apps",
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
  @"subscribed_fields": @"leadgen",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/subscribed_apps"
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
  -F 'subscribed_fields="leadgen"' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{page-id}/subscribed_apps
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `subscribed_fields`  array<enum {feed, mention, name, picture, category, description, conversations, agent\_messages, agent\_questions, feature\_access\_list, inbox\_labels, standby, message\_mention, messages, message\_reactions, messaging\_account\_linking, messaging\_checkout\_updates, messaging\_customer\_information, message\_echoes, message\_edits, message\_deliveries, message\_context, messaging\_game\_plays, messaging\_optins, messaging\_optouts, messaging\_payments, messaging\_postbacks, messaging\_pre\_checkouts, message\_reads, messaging\_referrals, messaging\_handovers, messaging\_policy\_enforcement, marketing\_message\_delivery\_failed, marketing\_message\_echoes, marketing\_message\_deliveries, marketing\_message\_clicks, marketing\_message\_reads, messaging\_appointments, messaging\_direct\_sends, messaging\_fblogin\_account\_linking, user\_action, messaging\_feedback, send\_cart, group\_feed, calls, call\_permission\_reply, call\_settings\_update, response\_feedback, messaging\_integrity, business\_integrity, messaging\_in\_thread\_lead\_form\_submit, message\_template\_status\_update, founded, company\_overview, mission, products, general\_info, leadgen, leadgen\_fat, leadgen\_update, location, hours, parking, public\_transit, page\_about\_story, mcom\_invoice\_change, invoice\_access\_invoice\_change, invoice\_access\_invoice\_draft\_change, invoice\_access\_onboarding\_status\_active, invoice\_access\_bank\_slip\_events, local\_delivery, phone, email, website, ratings, attire, payment\_options, culinary\_team, general\_manager, price\_range, awards, hometown, current\_location, bio, affiliation, birthday, personal\_info, personal\_interests, members, checkins, page\_upcoming\_change, page\_change\_proposal, merchant\_review, product\_review, videos, live\_videos, video\_text\_question\_responses, registration, payment\_request\_update, publisher\_subscriptions, invalid\_topic\_placeholder, marketing\_messages\_subscriber\_upload\_status, follow, story\_share, comment\_poll\_response, story\_poll\_response}> | Page Webhooks fields that you want to subscribe  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 100 | Invalid parameter |
| 104 | Incorrect signature |
| 210 | User not visible |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 102 | Session key invalid or no longer valid |

## Updating

You can't perform this operation on this endpoint.

## Deleting

Unsubscribe your app to a [Webhook](/docs/graph-api/webhooks/getting-started/webhooks-for-pages) for a Facebook Page.

### Permissions

An app can remove its own webhook subscription from a Page with an App Access Token.

You can dissociate an [Application](/docs/graph-api/reference/application/) from a [Page](/docs/graph-api/reference/page/) by making a DELETE request to [`/{page_id}/subscribed_apps`](/docs/graph-api/reference/page/subscribed_apps/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

`messaging_success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 210 | User not visible |
| 200 | Permissions error |
| 104 | Incorrect signature |
