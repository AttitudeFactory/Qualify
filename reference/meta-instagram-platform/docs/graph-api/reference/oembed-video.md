Graph API Version

[v25.0](#)

# Oembed Video

On April 8, 2025, we introduced a new oEmbed feature, [**Meta oEmbed Read**](https://developers.facebook.com/docs/features-reference/meta-oembed-read) to replace the existing oEmbed Read feature. The current [oEmbed Read feature](https://developers.facebook.com/docs/features-reference/oembed-read) will be deprecated on November 3, 2025.

* Apps created after April 8, 2025 that implement oEmbed will use the new Meta oEmbed Read feature.
* Existing apps that already use the current oEmbed Read feature will be automatically updated to the new Meta oEmbed Read feature by November 3, 2025.


The following fields are no longer returned and will be fully deprecated on November 3, 2025:

* `author_name`
* `author_url`
* `thumbnail_height`
* `thumbnail_url`
* `thumbnail_width`


Read the [oEmbed Updates blog post](https://developers.facebook.com/blog/post/2025/04/08/oembed-updates/) from Meta to learn more.

On June 15, 2026, we lifted the access token requirement from all Meta oEmbed APIs. This applies to the following endpoints:

* [`Threads oEmbed`](https://developers.facebook.com/docs/threads/tools-and-resources/embed-a-threads-post)
* [`Instagram oEmbed`](https://developers.facebook.com/docs/instagram-platform/oembed/)
* [`Facebook oEmbed Post`](https://developers.facebook.com/docs/graph-api/reference/oembed-post/)
* [`Facebook oEmbed Video`](https://developers.facebook.com/docs/graph-api/reference/oembed-video/)


This means that App Review will no longer be required to embed public Meta content. With tokenless access, you can make up to 1,000 oEmbed API requests per endpoint every hour. If you already have the [Meta oEmbed Read](https://developers.facebook.com/docs/features-reference/meta-oembed-read/) or [Threads oEmbed Read](https://developers.facebook.com/docs/features-reference/threads-oembed-read/) feature approved through App Review, you can still use an access token to make up to 5 million oEmbed API requests per endpoint every day.

Read the Introducing Tokenless Access to [Meta oEmbed APIs blog post](https://developers.facebook.com/blog/post/2026/06/15/tokenless-access-to-meta-oembed-apis/) from Meta to learn more.

## Reading

OembedVideo

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=oembed_video&version=v25.0)

```
GET /v25.0/oembed_video HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/oembed_video',
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
    "/oembed_video",
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
    "/oembed_video",
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
                               initWithGraphPath:@"/oembed_video"
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
| `maxwidth`  int64 | maxwidth |
| `omitscript`  boolean | Default value: `false`  omitscript |
| `sdklocale`  string | sdklocale |
| `url`  URI | url  Required |
| `useiframe`  boolean | Default value: `false`  useiframe |

### Fields

| Field | Description |
| --- | --- |
| `height`  int32 | height  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `html`  string | html  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_name`  string | provider\_name  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_url`  string | provider\_url  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  string | type  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `version`  string | version  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `width`  int32 | width  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
