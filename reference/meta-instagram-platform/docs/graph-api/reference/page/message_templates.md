Graph API Version

[v25.0](#)

# Page Message Templates

### Requirements

The following table contains the requirements for all API calls to the endpoints defined in this reference.

Requirement | Description || Access token type | Page |
| Permission | `page_utility_messaging` |

## Reading

Get a list of message templates owned or managed by your app user's Facebook Page.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fmessage_templates&version=v25.0)

```
GET /v25.0/{page-id}/message_templates HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/message_templates',
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
    "/{page-id}/message_templates",
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
    "/{page-id}/message_templates",
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
                               initWithGraphPath:@"/{page-id}/message_templates"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Request syntax

```
GET /<PAGE_ID>/message_templates
  ?category=<CATEGORY>,
  &content=<CONTENT>,
  &language=<LANGUAGE>,
  &name=<NAME>,
  &name_or_content=<NAME_OR_CONTENT>,
  &status=<STATUS>
```

#### Sample response

```
{
  "data": [
    "name": "order_delivery_update_1",
      "components": [
        {
          "type": "BODY",
          "text": "Good news {{1}}! Your order #{{2}} is on its way. Thank you!",
          "example": {
            "body_text": [
              [
                "Mark",
                "566701"
              ]
            ]
          }
        },
        {
          "type": "BUTTONS",
          "buttons": [
            {
              "type": "POSTBACK",
              "text": "Track Order",
              "payload": "track_order"
            },
            {
              "type": "POSTBACK",
              "text": "Stop Delivery Update",
              "payload": "stop_delivery_update"
            }
          ]
        }
      ],
      "language": "en",
      "status": "APPROVED",
      "category": "UTILITY",
      "id": "12345678910123"
    },
    ...
  ],
  "paging": {
    "cursors": {
      "before": "MAZDZD",
      "after": "MjQZD"
    }
  }
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `category`  array<enum {UTILITY}> | The message template category. |
| `content`  string | The content of the template. |
| `language`  array<string> | A list of supported languages that are available for each template. |
| `name`  string | The name of the template. |
| `name_or_content`  string | A list of message templates where the name or content match this value. |
| `status`  array<enum {APPROVED, IN\_APPEAL, PENDING, REJECTED, PENDING\_DELETION, DELETED, DISABLED, PAUSED, LIMIT\_EXCEEDED, ARCHIVED}> | The review status of the template. |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `message_templates` edge from the following paths:

* [`/{page_id}/message_templates`](/docs/graph-api/reference/page/message_templates/)

When posting to this edge, a [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) will be created.

### Examples

#### Sample request

To create a utility message template, send a `POST` request to the `/<PAGE_ID>/message_templates` endpoint with the following required parameters:

* `name` set to the name of the template
* `language` set to the language of the message text
* `category` set to `UTILITY`
* `components` set to an array of message components including an example with message values

### Parameter Formats

Templates support two parameter formats:

* **Named parameters** — Placeholders use descriptive names: `{{customer_name}}`, `{{order_id}}`. Set `parameter_format` to `NAMED` when creating the template. Example values are provided in the `body_text_named_params` and `header_text_named_params` fields using `param_name` and `example` pairs.
* **Positional parameters** (default) — Placeholders use sequential numbers: `{{1}}`, `{{2}}`, `{{3}}`. Example values are provided in the `body_text` and `header_text` fields. This is the default format when `parameter_format` is not specified.

#### Text-Only Templates (Named Parameters)

In the following example, we use named parameters with descriptive placeholder names. The `parameter_format` is set to `NAMED`, and example values are provided using `body_text_named_params` and `header_text_named_params` with `param_name` and `example` pairs.

```
curl -H 'Content-Type: application/json' \
     -d '{
           "name": "jaspers_market_order_delivery_update_named_us",
           "language": "en",
           "category": "UTILITY",
           "parameter_format": "NAMED",
           "components": [
            {
              "type": "HEADER",
              "format": "TEXT",
              "text":"{{order_type}} Update",
              "example": {
               "header_text_named_params": [
                 {
                   "param_name": "order_type",
                   "example": "Order"
                 }
               ]
              }
             },
             {
               "type": "BODY",
               "text": "Good news! Your order #{{order_id}} is on its way. Thank you for your order, {{customer_name}}!",
               "example": {
                 "body_text_named_params": [
                   {
                     "param_name": "order_id",
                     "example": "566701"
                   },
                   {
                     "param_name": "customer_name",
                     "example": "John"
                   }
                 ]
               }
             }
           ]
         }' "https://graph.facebook.com/v25.0/102290129340398/message_templates?access_token=EAAJB..."
```

#### Text-Only Templates (Positional Parameters)

In the following example, we have message body text and header text. The body component and header component includes example customer information that would be used to customize the message.

```
curl -H 'Content-Type: application/json' \
     -d '{
           "name": "jaspers_market_order_delivery_update_us",
           "language": "en",
           "category": "UTILITY",
           "components": [
            {
              "type": "HEADER",
              "format": "TEXT",
              "text":"{{1}} Update",
              "example": {
               "header_text":["Order"]
              }
             },
             {
               "type": "BODY",
               "text": "Good news! Your order #{{1}} is on its way. Thank you for your order!",
               "example": {
                 "body_text": [
                   [
                     "566701"
                   ]
                 ]
               }
             }
           ]
         }' "https://graph.facebook.com/v25.0/102290129340398/message_templates?access_token=EAAJB..."
```

#### Text + Image Templates

You can also create templates with images. Images need to be first uploaded using the [Resumable Upload API](https://developers.facebook.com/docs/graph-api/guides/upload) to generate the handle for the image. You can then use the handle and pass it in the Header component while creating the template.

```
curl -H 'Content-Type: application/json' \
     -d '{
           "name": "jaspers_market_order_delivery_update_named_us",
           "language": "en",
           "category": "UTILITY",
           "parameter_format": "NAMED",
           "components": [
             {
              "type": "HEADER",
              "format": "IMAGE",
              "text":"{{order_type}} Update",
              "example": {
               "header_handle": ["4:dGVzdF9pbWFn......."],
               "header_text_named_params": [
                 {
                   "param_name": "order_type",
                   "example": "Order"
                 }
               ]
              }
             },
             {
               "type": "BODY",
               "text": "Good news! Your order #{{order_id}} is on its way. Thank you for your order, {{customer_name}}!",
               "example": {
                 "body_text_named_params": [
                   {
                     "param_name": "order_id",
                     "example": "566701"
                   },
                   {
                     "param_name": "customer_name",
                     "example": "John"
                   }
                 ]
               }
             }
           ]
         }' "https://graph.facebook.com/v25.0/102290129340398/message_templates?access_token=EAAJB..."
```

On success your app receives a JSON response with the template ID, the review status, and the template category.

```
{
  "id": "104595129340398",
  "status": "APPROVED",
  "category": "UTILITY"
}
```

#### Sample response

```
{
    "id": "594425479261596",
    "status": "PENDING",
    "category": "UTILITY"
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `category`  enum {UTILITY} | Required. The category of the template.  Required |
| `components`  array<JSON object> | An array of objects to be included in the message. Can include the header, body, and buttons (phone number, postback, URL). |
| `type`  enum {HEADER, BODY, BUTTONS} | Component type.  Required |
| `format`  enum {TEXT, IMAGE} | Component format. |
| `text`  string | **Required for components with type `HEADER`,`BODY`**  Component text. |
| `buttons`  array<JSON object> | Button components to be used in the template. |
| `type`  enum {QUICK\_REPLY, URL, PHONE\_NUMBER, OTP, MPM, CATALOG, FLOW, VOICE\_CALL, VIDEO\_CALL, POSTBACK, BOOKING\_STATUS, PAYMENT\_REQUEST, REQUEST\_CONTACT\_INFO} | type  Required |
| `text`  string | text |
| `url`  URI | url |
| `phone_number`  phone number string | phone\_number |
| `example`  array<string> | example |
| `payload`  string | payload |
| `example`  JSON object | Placeholder examples. Templates will not be approved without examples. |
| `header_text`  array<string> | header\_text |
| `body_text`  array<array<string>> | body\_text |
| `header_handle`  array<string> | header\_handle |
| `header_text_named_params`  array<JSON object> | header\_text\_named\_params |
| `param_name`  string | param\_name  Required |
| `example`  string | example  Required |
| `body_text_named_params`  array<JSON object> | body\_text\_named\_params |
| `param_name`  string | param\_name  Required |
| `example`  string | example  Required |
| `language`  string | The language of the message. For example, en\_US.  Required |
| `library_template_button_inputs`  array<JSON object> | An array of objects that define the type of button and it's contents and actions. |
| `type`  enum {QUICK\_REPLY, URL, PHONE\_NUMBER, OTP, MPM, CATALOG, FLOW, VOICE\_CALL, VIDEO\_CALL, POSTBACK, BOOKING\_STATUS, PAYMENT\_REQUEST, REQUEST\_CONTACT\_INFO} | type  Required |
| `phone_number`  string | phone\_number |
| `url`  JSON object | url |
| `base_url`  string | base\_url  Required |
| `url_suffix_example`  string | url\_suffix\_example |
| `library_template_name`  string | The name of the library the template belongs to. |
| `name`  string | The name of the template.  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`id`: numeric string,

`status`: enum,

`category`: enum,

`rejection_reason`: enum,

`specific_rejection_reason`: enum,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can dissociate a [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) from a [Page](/docs/graph-api/reference/page/) by making a DELETE request to [`/{page_id}/message_templates`](/docs/graph-api/reference/page/message_templates/).

### Example

#### Sample request

```
curl -X DELETE "https://graph.facebook.com/v25.0/102290129340398/message_templates?name=order_confirmation&access_token=EAAJB..."
```

#### Sample response

```
{
  "success": true
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `name`  string | The name of the template to be deleted in all languages, if no template\_id is provided.  Required |
| `template_id`  numeric string | Optional. Limits the deletion of template to the template\_id provided. |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |

## Error codes

Error | Description || 32 | Your app is rate limited. There have been too many calls to this Page. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 100 | Invalid parameter. Check spelling and availability of the parameter for the enpoint in your call. |
| 190 | Invalid OAuth 2.0 Access Token. Use the [Access token debugger tool](https://developers.facebook.com/tools/debug/accesstoken) to help you debug this issue. |
| 200 | Permissions error. The API call is missing a permission. Use the [Access token debugger tool](https://developers.facebook.com/tools/debug/accesstoken) to help you debug this issue. |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed. |
| 131009 | Parameter value is not valid. |
| 200002 | Template creation failed. |
