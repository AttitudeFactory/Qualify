Graph API Version

[v25.0](#)

# Page Published Posts

## Reading

PagePublishedPosts

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fpublished_posts&version=v25.0)

```
GET /v25.0/{page-id}/published_posts HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/published_posts',
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
    "/{page-id}/published_posts",
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
    "/{page-id}/published_posts",
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
                               initWithGraphPath:@"/{page-id}/published_posts"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Limitations

* **Maximum Posts**
  + The API will return approximately 600 ranked, published posts per year.
  + You can only read a maximum of 100 feed posts with the `limit` field. If you try to read more than that you will get an error message to not exceed 100.
* **Message CTA** - Posts with message CTAs cannot be accessed using another Page's access token since Pages cannot message other Pages.
* **Publicly Identifiable Information** - User information will not be included in responses unless you make the request with a Page access token.
* **Shared Posts** - A Page post which shares a post from another Page or person may not be visible if the original post isn't visible with the access token used.
* **Tagged Posts** - When you use `/{page-id}/tagged` to show the posts that tagged this Page, the results include posts from other Pages only if those Pages are authentic.
* **User Agents** - The available user agents allowed for these Graph API calls are subject to change without notice. If you are experiencing issues, you may want to change to a newer version of your particular user agent.
* **Video Posts** - The `source` field for `/page/feed` and `/page/posts` will only be returned for Page-owned videos when the User making the request is an admin of the owning Page.

### Parameters

This endpoint doesn't have any parameters.

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

A list of [PagePost](/docs/graph-api/reference/page-post/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=total_count`).

| Field | Description |
| --- | --- |
| `total_count`  unsigned int32 | total\_count |

### Error Codes

| Error | Description |
| --- | --- |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 210 | User not visible |
| 190 | Invalid OAuth 2.0 Access Token |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 104 | Incorrect signature |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
