Graph API Version

[v25.0](#)

# Messenger Business Template

## Reading

Messenger schema for business message templates used for business messaging

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bmessenger-business-template-id%7D&version=v25.0)

```
GET /v25.0/{messenger-business-template-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{messenger-business-template-id}',
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
    "/{messenger-business-template-id}",
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
    "/{messenger-business-template-id}",
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
                               initWithGraphPath:@"/{messenger-business-template-id}"
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

| Field | Description |
| --- | --- |
| `id`  numeric string | The ID for the business template |
| `category`  enum | The business template category  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `components`  list<MessengerBusinessTemplateWhatsAppHSMComponentGet> | The components included in this template  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creation_time`  integer | Creation time of the template |
| `language`  string | The languages in which this template is available  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `language_count`  integer | The number of languages this template |
| `last_updated_time`  datetime | The time at which this template was last updated |
| `library_template_name`  string | The name of the template library that this template belongs  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | The name of this template  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `parameter_format`  enum | parameter\_format |
| `rejected_reason`  enum | The reason this template was rejected |
| `rejection_reasons`  MessengerBusinessTemplateWhatsAppBusinessHSMRejectionReasons | The reasons this template was rejected |
| `specific_rejection_reasons`  MessengerBusinessTemplateWhatsAppBusinessHSMSpecificRejectionReasons | The specific reasons this template was rejected |
| `status`  enum | The status of this template  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `message_templates` edge from the following paths:

* [`/{page_id}/message_templates`](/docs/graph-api/reference/page/message_templates/)

When posting to this edge, a [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) will be created.

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

You can update a [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) by making a POST request to [`/{messenger_business_template_id}`](/docs/graph-api/reference/messenger-business-template/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `components`  array<JSON object> | Update the components in this template |
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

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

`status`: enum,

`rejection_reason`: enum,

`specific_rejection_reason`: enum,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Deleting

You can dissociate a [MessengerBusinessTemplate](/docs/graph-api/reference/messenger-business-template/) from a [Page](/docs/graph-api/reference/page/) by making a DELETE request to [`/{page_id}/message_templates`](/docs/graph-api/reference/page/message_templates/).

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
