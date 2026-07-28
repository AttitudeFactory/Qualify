# Ad Adrules Governed



## Reading

Ad rules that govern this ad - by default, this only returns rules that either directly mention the ad by id or indirectly through the set entity_type

#### Example

### HTTP
```
GET /v25.0/&#123;ad-id&#125;/adrules_governed HTTP/1.1
Host: graph.facebook.com
```

### PHP SDK
```
/* PHP SDK v5.0.0 */
/* make the API call */
try &#123;
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb-&gt;get(
    &#039;/&#123;ad-id&#125;/adrules_governed&#039;,
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
    &quot;/&#123;ad-id&#125;/adrules_governed&quot;,
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
    &quot;/&#123;ad-id&#125;/adrules_governed&quot;,
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
                               initWithGraphPath:&#064;&quot;/&#123;ad-id&#125;/adrules_governed&quot;
                                      parameters:params
                                      HTTPMethod:&#064;&quot;GET&quot;];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) &#123;
    // Handle the result
&#125;];
```

Try it in [Graph API Explorer](https://developers.facebook.com/tools/explorer/?method=GET&amp;path=%7Bad-id%7D%2Fadrules_governed&amp;version=v25.0)

If you want to learn how to use the Graph API, read our [Using Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api)

#### Parameters

| Parameter | Description |
| --- | --- |
| `pass_evaluation`&lt;br&gt;&lt;br&gt;*boolean* | If set, this will further filter the rules to only include those for which the ad would evaluate to the boolean value of this param&lt;br&gt; |

#### Fields

Reading from this edge will return a JSON formatted result:

```
&#123;
&quot;data&quot;: [],
&quot;paging&quot;: &#123;&#125;
&#125;
```

##### data

A list of [AdRule](https://developers.facebook.com/docs/marketing-api/reference/ad-rule) nodes.

##### paging

For more details about pagination, see the [Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api#paging).

#### Error Codes

| Error Code | Description |
| --- | --- |
| 104 | Incorrect signature |

## Creating

You can&#039;t perform this operation on this endpoint.

## Updating

You can&#039;t perform this operation on this endpoint.

## Deleting

You can&#039;t perform this operation on this endpoint.

