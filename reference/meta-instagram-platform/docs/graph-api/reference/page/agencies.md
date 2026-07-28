Graph API Version

[v25.0](#)

# Page Agencies

## Reading

Returns the Businesses and Agencies that have permissions on the page.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Requirements

* A Page access token requested by a person who can perform the `MANAGE` task on the Page.
* The `business_management` permission for Pages owned or claimed by a business, otherwise the `pages_manage_metadata` and `page_show_list` permissions.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fagencies&version=v25.0)

```
GET /v25.0/{page-id}/agencies HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/agencies',
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
    "/{page-id}/agencies",
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
    "/{page-id}/agencies",
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
                               initWithGraphPath:@"/{page-id}/agencies"
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

A list of [Business](/docs/marketing-api/reference/business/) nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `access_requested_time`  datetime | The creation time of the access request  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `access_status`  enum | The status of the access request  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `access_updated_time`  datetime | The update time of the access request  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `permitted_tasks`  list<string> | The permissions of tasks associated with the access request  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |

## Creating

You can make a POST request to `agencies` edge from the following paths:

* [`/{page_id}/agencies`](/docs/graph-api/reference/page/agencies/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `business`  numeric string | The business ID of the agency that you want to assign to this Page.  Required |
| `permitted_tasks`  array<enum {MANAGE, CREATE\_CONTENT, MODERATE, MESSAGING, ADVERTISE, ANALYZE, MODERATE\_COMMUNITY, MANAGE\_JOBS, PAGES\_MESSAGING, PAGES\_MESSAGING\_SUBSCRIPTIONS, READ\_PAGE\_MAILBOXES, VIEW\_MONETIZATION\_INSIGHTS, MANAGE\_LEADS, PROFILE\_PLUS\_FULL\_CONTROL, PROFILE\_PLUS\_MANAGE, PROFILE\_PLUS\_FACEBOOK\_ACCESS, PROFILE\_PLUS\_CREATE\_CONTENT, PROFILE\_PLUS\_MODERATE, PROFILE\_PLUS\_MODERATE\_DELEGATE\_COMMUNITY, PROFILE\_PLUS\_MESSAGING, PROFILE\_PLUS\_ADVERTISE, PROFILE\_PLUS\_ANALYZE, PROFILE\_PLUS\_REVENUE, PROFILE\_PLUS\_MANAGE\_LEADS, PROFILE\_PLUS\_CREATIVE\_MANAGEMENT, PROFILE\_PLUS\_CREATOR\_MANAGEMENT, CASHIER\_ROLE, GLOBAL\_STRUCTURE\_MANAGEMENT, PROFILE\_PLUS\_GLOBAL\_STRUCTURE\_MANAGEMENT}> | Tasks that are assignable to this Page. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 3989 | You are trying to assign a duplicated asset to this agency. |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 3946 | Asset already belongs to this Business Manager. |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
