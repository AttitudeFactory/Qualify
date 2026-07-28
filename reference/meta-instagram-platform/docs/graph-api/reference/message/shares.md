Graph API Version

[v25.0](#)

# Graph API Reference [`/{message-id}`](/docs/graph-api/reference/message/)`/shares`

As part of the V3.3 changes the `read_page_mailboxes` permission was deprecated. Use `pages_messaging` permission to access this endpoint.
The `read_page_mailboxes` permission will stop working after June 30 2020

Shared items in a message. This is a Pages-only endpoint.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bmessage-id%7D%2Fshares&version=v25.0)

```
GET /v25.0/{message-id}/shares HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{message-id}/shares',
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
    "/{message-id}/shares",
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
    "/{message-id}/shares",
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
                               initWithGraphPath:@"/{message-id}/shares"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

## Permissions

This edge requires a Page access token with the following permissions:

* `pages_messaging`

Apps in [Development Mode](/docs/apps/managing-development-cycle), are restricted to message people that have a role in the app.

### Fields

Name | Description | Type || `description` | The description of the shared item. | `string` |
| `link` | The URL to the shared item. | `string` |
| `id` | The shared item ID. | `string` |
| `name` | The title of the shared item. | `string` |
| `template` | The object of the shared item. | `Object` |

### `template.payload.product.elements`

This will only be available if the business can view the product. For products that are not owned by the business, it will return `shares.data.name` as `Attachment Unavailable`.

Property | Type | Description || `id` | String | Product ID from [Facebook product catalog](https://developers.facebook.com/docs/marketing-api/catalog/overview) |
| `retailer_id` | String | External ID that is associated with the Product. (ex: SKU/ Content ID) |
| `image_url` | String | URL of product image |
| `title` | String | Title of product |
| `price` | String | Price of product |

### Example of product template

Product template on Conversation API is only available on Graph API v8.0+

App will need to have [`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management) permission approved to receive product details in Conversation API.

```
"shares": {
    "data": [{
       "template": {
            "payload":{
                "product": {
                    "elements":{ // multiple elements in Hscroll
                        "data": [
                            {
                                "id" : "<Product_id>",
                                "retailer_id": "<EXTERNAL_ID>",
                                "image_url" : "https://fb.cdn.com/sdsd",
                                "name" : "Some product title",
                                "price" : "$10"
                            },
                            {..}],
                        }
                    }
                }
            }
    }]
}
```

## Publishing

You can't publish using this edge.

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.
