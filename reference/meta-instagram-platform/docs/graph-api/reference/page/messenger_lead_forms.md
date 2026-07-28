Graph API Version

[v25.0](#)

# Page Messenger Lead Forms

## Reading

Read all messenger\_lead\_forms owned by the page

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fmessenger_lead_forms&version=v25.0)

```
GET /v25.0/{page-id}/messenger_lead_forms HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/messenger_lead_forms',
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
    "/{page-id}/messenger_lead_forms",
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
    "/{page-id}/messenger_lead_forms",
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
                               initWithGraphPath:@"/{page-id}/messenger_lead_forms"
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

A list of [MessengerAdsPartialAutomatedStepList](/docs/marketing-api/reference/messenger-ads-partial-automated-step-list/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 80005 | There have been too many leadgen api calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 210 | User not visible |
| 190 | Invalid OAuth 2.0 Access Token |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `messenger_lead_forms` edge from the following paths:

* [`/{page_id}/messenger_lead_forms`](/docs/graph-api/reference/page/messenger_lead_forms/)

When posting to this edge, a [Page](/docs/graph-api/reference/page/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `account_id`  int64 | ID of the account |
| `block_send_api`  boolean | Whether to block messages sent using Send API while user is in Lead Gen Experience |
| `handover_app_id`  int64 | Hand over thread to specified app after leadgen is complete |
| `handover_summary`  boolean | Opt-in to get a summary message sent to the target HOP app at the end of the automated flow |
| `privacy_url`  URI | Privacy URL for Messenger Lead Gen Experience |
| `reminder_text`  string | Reminder text that will be sent to user after inactivity |
| `step_list`  array<JSON object> | List of steps in Messenger Lead Gen Experience  Required |
| `step_id`  int64 | step\_id  Required |
| `message`  string | message  Required |
| `step_type`  enum {QUESTION, CONFIRMATION, DISCLAIMER, DISQUALIFY, INFO, INTRO, SUMMARY, POST\_LEAD\_TRANSITION} | step\_type  Required |
| `reply_type`  enum {QUICK\_REPLIES, BUTTON\_XMA, TEXT, NONE, PREFILL, ICE\_BREAKERS, APPOINTMENT, SUBSCRIBE, CALL\_PREFERENCE, CONDITIONAL\_ANSWER} | reply\_type  Required |
| `answers`  array<string> | Default value: `[]`  answers |
| `next_step_ids`  array<int64> | Default value: `[]`  next\_step\_ids |
| `prefill_type`  enum {FULL\_ADDRESS, STREET\_ADDRESS, ZIP\_CODE, POST\_CODE, CITY, STATE, PROVINCE, COUNTRY, EMAIL, PHONE, JOB\_TITLE, COMPANY\_NAME, GENDER, DOB, DATE\_TIME, SLIDER, NONE, FIRST\_NAME, LAST\_NAME, FULL\_NAME, RELATIONSHIP\_STATUS, MARITAL\_STATUS, MILITARY\_STATUS, WORK\_EMAIL, WORK\_PHONE, NATIONAL\_ID\_BRAZIL, NATIONAL\_ID\_ARGENTINA, NATIONAL\_ID\_PERU, NATIONAL\_ID\_CHILE, NATIONAL\_ID\_COLOMBIA, NATIONAL\_ID\_ECUADOR, NATIONAL\_ID\_MEXICO} | Default value: `"NONE"`  prefill\_type |
| `crm_field_id`  string | crm\_field\_id |
| `answer_crm_field_ids`  array<string> | Default value: `[]`  answer\_crm\_field\_ids |
| `media_type`  enum {TEXT, IMAGE, VIDEO} | media\_type |
| `media_content`  string | media\_content |
| `options_format`  enum {TEXT, CAROUSEL} | Default value: `"TEXT"`  options\_format |
| `carousel_answers`  array<JSON object> | Default value: `[]`  carousel\_answers |
| `value`  string | value  Required |
| `media_content`  string | media\_content  Required |
| `answer_validation_enabled`  boolean | answer\_validation\_enabled |
| `invalid_reply_text`  string | invalid\_reply\_text |
| `cta`  JSON object | cta |
| `cta_type`  enum {VIEW\_WEBSITE, CALL\_BUSINESS, MESSAGE\_BUSINESS, DOWNLOAD, SCHEDULE\_APPOINTMENT, VIEW\_ON\_FACEBOOK, PROMO\_CODE, NONE, WHATSAPP, P2B\_MESSENGER, BOOK\_ON\_WEBSITE} | cta\_type  Required |
| `cta_text`  string | cta\_text  Required |
| `cta_content`  string | cta\_content  Required |
| `allow_to_skip`  boolean | allow\_to\_skip |
| `qualifying_answers_list`  array<string> | qualifying\_answers\_list |
| `next_step_on_disqualification_id`  int64 | next\_step\_on\_disqualification\_id |
| `offer_code_file_id`  int64 | offer\_code\_file\_id |
| `offer_code`  string | offer\_code |
| `offer_code_format`  string | offer\_code\_format |
| `stop_question_message`  string | Confirmation message after user clicks on the Stop Question option in persistent menu |
| `template_name`  string | Name for the form |
| `tracking_parameters`  JSON object {string : string} | Tracking Parameters of Lead Forms |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
