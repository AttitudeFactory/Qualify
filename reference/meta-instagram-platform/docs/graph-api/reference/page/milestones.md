This document refers to a feature that was removed after [Graph API v3.2.](/docs/graph-api/reference/v3.2/page/milestones)

Graph API Version

[v25.0](#)

# Graph API Reference [`/{page-id}`](/docs/graph-api/reference/page/)`/milestones`

The [milestones](https://www.facebook.com/help/279680818764230) posted by a Facebook Page.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fmilestones&version=v25.0)

```
GET /v25.0/{page-id}/milestones HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/milestones',
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
    "/{page-id}/milestones",
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
    "/{page-id}/milestones",
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
                               initWithGraphPath:@"/{page-id}/milestones"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* Any valid app or user access token is needed to view publicly shared milestones.
* A page access token is required to view any other milestones.

### Fields

An array of [Milestone objects](/docs/graph-api/reference/milestone/).

## Publishing

You can create Page milestones by using this edge:

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{page-id}/milestones HTTP/1.1
Host: graph.facebook.com

title=Final+Episode+Aired&description=The+big+finale+was+today%21&start_time=2013-09-29T21%3A00%3A00%2B0500
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{page-id}/milestones',
    array (
      'title' => 'Final Episode Aired',
      'description' => 'The big finale was today!',
      'start_time' => '2013-09-29T21:00:00+0500',
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
    "/{page-id}/milestones",
    "POST",
    {
        "title": "Final Episode Aired",
        "description": "The big finale was today!",
        "start_time": "2013-09-29T21:00:00+0500"
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
params.putString("title", "Final Episode Aired");
params.putString("description", "The big finale was today!");
params.putString("start_time", "2013-09-29T21:00:00+0500");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/milestones",
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
  @"title": @"Final Episode Aired",
  @"description": @"The big finale was today!",
  @"start_time": @"2013-09-29T21:00:00+0500",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/milestones"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A page access token can be used to publish new milestones on behalf of that page.

### Fields

| Name | Description | Type |
| --- | --- | --- |
| `title` | The title of the milestone. | `string` |
| `description` | The description of the milestone. | `string` |
| `start_time` | The start time of the milestone. This will also be used for the `end_time` value (these two fields are always the same). | `datetime` |

### Response

If successful:

| Name | Description | Type |
| --- | --- | --- |
| `id` | The newly created milestone ID | `string` |

## Deleting

You can't delete using this edge, however you can [delete milestones using the /{milestone-id} node](/docs/graph-api/reference/milestone/).

## Updating

You can't update using this edge, however you can [update milestones using the /{milestone-id} node](/docs/graph-api/reference/milestone/).
