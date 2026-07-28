# Ad Creative



Contains content for an ad, including images, videos and so on.

## Reading

#### Example

### HTTP
```
GET /v25.0/&#123;ad-id&#125;/adcreatives HTTP/1.1
Host: graph.facebook.com
```

### PHP SDK
```
/* PHP SDK v5.0.0 */
/* make the API call */
try &#123;
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb-&gt;get(
    &#039;/&#123;ad-id&#125;/adcreatives&#039;,
    &#039;&#123;access-token&#125;&#039;
  );
&#125; catch(Facebook\Exceptions\FacebookResponseException $e) &#123;
  echo &#039;Graph returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125; catch(Facebook\Exceptions\FacebookSDKException $e) &#123;
  echo &#039;Facebook SDK returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125;
$graphNode = $response-&gt;getGraphNode();
/* handle the result */
```

### JavaScript SDK
```
/* make the API call */
FB.api(
    &quot;/&#123;ad-id&#125;/adcreatives&quot;,
    function (response) &#123;
      if (response &amp;&amp; !response.error) &#123;
        /* handle the result */
      &#125;
    &#125;
);
```

### Android SDK
```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    &quot;/&#123;ad-id&#125;/adcreatives&quot;,
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() &#123;
        public void onCompleted(GraphResponse response) &#123;
            /* handle the result */
        &#125;
    &#125;
).executeAsync();
```

### iOS SDK
```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:&#064;&quot;/&#123;ad-id&#125;/adcreatives&quot;
                                      parameters:params
                                      HTTPMethod:&#064;&quot;GET&quot;];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) &#123;
    // Handle the result
&#125;];
```

Try it in [Graph API Explorer](https://developers.facebook.com/tools/explorer/?method=GET&amp;path=%7Bad-id%7D%2Fadcreatives&amp;version=v25.0)

If you want to learn how to use the Graph API, read our [Using Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api)

#### Parameters

This endpoint doesn&#039;t have any parameters.

#### Fields

Reading from this edge will return a JSON formatted result:

```
&#123;
&quot;data&quot;: [],
&quot;paging&quot;: &#123;&#125;
&#125;
```

##### data

A list of [AdCreative](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-creative) nodes.

##### paging

For more details about pagination, see the [Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api#paging).

#### Error Codes

| Error Code | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to /docs/graph-api/overview/rate-limiting#ads-management. |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |
| 2500 | Error parsing graph query |

## Creating

You can&#039;t perform this operation on this endpoint.

## Updating

You can&#039;t perform this operation on this endpoint.

## Deleting

You can&#039;t perform this operation on this endpoint.

