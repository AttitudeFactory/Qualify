Graph API Version

[v25.0](#)

# Page Locations

This represents different page locations of a parent business Page. For example, pages for each restaurant in a chain of restaurants.

Reading this edge is available to all apps. Some types of publishing operations are only available to select developers.

When using the publishing operations of this API please follow these guidelines:

* Don't charge a fee for creating or claiming a Page.
* Before enabling clients to create a Page, you must first provide a means for them to claim an existing Place to prevent Page duplication.
* Ensure that you only create Pages associated with a real physical address, not fake or virtual Places.
* If you create a Page on a client's behalf, you must transfer full administration of that Page upon the client's request.
* Don't disclose administrators of a Page to third parties without the client's consent, except as required by any applicable law, by any rule or regulation of any court or government agency of competent jurisdiction, or pursuant to legal process.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Flocations&version=v25.0)

```
GET /v25.0/{page-id}/locations HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/locations',
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
    "/{page-id}/locations",
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
    "/{page-id}/locations",
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
                               initWithGraphPath:@"/{page-id}/locations"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* Any valid access token is required to retrieve locations.

### Fields

An array of [Page objects](/docs/graph-api/reference/page/), each representing an individual location for the business.

## Publishing

You can add an existing location-based Page to this list by publishing on this edge:

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{page-id}/locations HTTP/1.1
Host: graph.facebook.com

main_page_id=%7Bpage-id%7D&store_number=12345&location_page_id=%7Bsubpage-id%7D
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{page-id}/locations',
    array (
      'main_page_id' => '{page-id}',
      'store_number' => '12345',
      'location_page_id' => '{subpage-id}',
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
    "/{page-id}/locations",
    "POST",
    {
        "main_page_id": "{page-id}",
        "store_number": "12345",
        "location_page_id": "{subpage-id}"
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
params.putString("main_page_id", "{page-id}");
params.putString("store_number", "12345");
params.putString("location_page_id", "{subpage-id}");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/locations",
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
  @"main_page_id": @"{page-id}",
  @"store_number": @"12345",
  @"location_page_id": @"{subpage-id}",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/locations"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A page access token is required to publish existing locations to a page.
* A page access token is required to create new locations and add them to a page. Only selected developers will have access to this functionality.

### Fields

Name | Description | Type || `differently_open_offerings` | To be used when `temporary_status` is set to `differently_open` to indicate how the business is operating differently than usual, such as a restaurant offering takeout. Enum keys can be one or more of the following: `ONLINE_SERVICES`, `DELIVERY`, `PICKUP`, `OTHER` with the value set to `true` or `false`. For example, a restaurant offering food pick up but pausing delivery would be `differently_open_offerings:{"DELIVERY":"false", "PICKUP":"true"}` | `object` |
| `hours` | Defines the opening hours for this location. | `object` |
| `{day}_{number}_{status}` | Defines a single opening hours range for a day. Each day can have 2 different hours ranges. `{day}` should be the first 3 characters of the day of the week, `{number}` should be either `1` or `2` to allow for the two different hours ranges per day. `{status}` should be either `open` or `close` to delineate the start or end of a time range. An example would be `mon_1_open` with value `17:00` and `mon_1_close` with value `21:15` which would represent a single opening range of 5pm to 9:15pm on Mondays. | `string` |
| `ignore_warnings` | Whether to disable any warnings (not errors) that result from this API call, such as latitude and longitude not matching street address. | `bool` |
| `is_franchise` | Is this a franchise location? | `bool` |
| `country` | Name of a country. If `city_id` is not included, then this is required. | `string` |
| `city` | Name of a city. If `city_id` is not included, then this is required. | `string` |
| `city_id` | ID of a city. This is the `key` value of the [`adcity` targeting options](/docs/graph-api/reference/targeting/). If this is not included, then `city` and `country` are required (`state` and `zip` are also required for locations in the USA). | `int` |
| `latitude` | Decimal based latitude. This is required for `location`. | `string` |
| `location` | This defines the location for this page. This is required if `location_page_id` is not specified. The dictionary must include the key `street` (street address). It also must include either `city_id` or all of `city`, `state`, and `country` (but `state` is optional if the address is not in the U.S.). The `zip` field is also optional unless it is a U.S. address. Please see later in this document for information about [generating a city id](#cityid). | `object` |
| `longitude` | Decimal based longitude. This is required for `location`. | `string` |
| `state` | Name of a state (or local equivalent). | `string` |
| `street` | Street address. This is required for `location`. | `string` |
| `zip` | Zip code of location (or local equivalent). | `string` |
| `location_page_id` | The ID of the Facebook Page you would like to add as a location. If this field is not included, you must instead specify `location`, `place_topics`, and `phone` fields to create a new location Page. | `numeric string` |
| `main_page_id` | The ID for the Facebook Page that is the parent of all the locations. This is a required field. | `numeric string` |
| `permanently_closed` | Is this location permanently closed? | `bool` |
| `phone` | Phone number for this location. This is required if `location_page_id` is not specified. | `string` |
| `pickup_options` | A list of pickup options available at this location. | `enum[] {CURBSIDE, IN_STORE, OTHER}` |
| `place_topics` | Place topics for this location. This is required if `location_page_id` is not specified. | `int[]` |
| `store_number` | An arbitrary, developer-defined ID for this location, usually used to link back to an internal database of locations. This is a required field. | `int` |
| `temporary_status` | Indicates how the business corresponding to a Page is operating differently than usual. If set to `differently_open` use with `differently_open_offerings` to set status. | enum {`differently_open`, `temporarily_closed`, `operating_as_usual`, `no_data`} |

### Response

Upon success, your app receives the following:

```
{
  "success": true
}
```

Otherwise a relevant error message will be returned.

## Deleting

You can remove a location page from a parent's list of locations by deleting on this edge:

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
DELETE /v25.0/{page-id}/locations HTTP/1.1
Host: graph.facebook.com

main_page_id=%7Bpage-id%7D&store_number=12345&location_page_id=%7Bsubpage-id%7D
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->delete(
    '/{page-id}/locations',
    array (
      'main_page_id' => '{page-id}',
      'store_number' => '12345',
      'location_page_id' => '{subpage-id}',
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
    "/{page-id}/locations",
    "DELETE",
    {
        "main_page_id": "{page-id}",
        "store_number": "12345",
        "location_page_id": "{subpage-id}"
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
params.putString("main_page_id", "{page-id}");
params.putString("store_number", "12345");
params.putString("location_page_id", "{subpage-id}");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/locations",
    params,
    HttpMethod.DELETE,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"main_page_id": @"{page-id}",
  @"store_number": @"12345",
  @"location_page_id": @"{subpage-id}",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/locations"
                                      parameters:params
                                      HTTPMethod:@"DELETE"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A page access token is required to remove locations from a parent page.

### Fields

All fields are required.

Name | Description | Type || `main_page_id` | ID of the main Facebook Page for this location. | `numeric string` |
| `store_number` | Developer-defined ID for this location. | `numeric string` |
| `location_page_id` | Facebook-defined ID for this location. | `numeric string` |

### Response

If successful:

```
{
  "success": true
}
```

Otherwise a relevant error message will be returned.

## Updating

This endpoint is supported for New Page Experience.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{page-id}/locations HTTP/1.1
Host: graph.facebook.com

main_page_id=%7Bpage-id%7D&store_number=12345&location_page_id=%7Bsubpage-id%7D
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{page-id}/locations',
    array (
      'main_page_id' => '{page-id}',
      'store_number' => '12345',
      'location_page_id' => '{subpage-id}',
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
    "/{page-id}/locations",
    "POST",
    {
        "main_page_id": "{page-id}",
        "store_number": "12345",
        "location_page_id": "{subpage-id}"
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
params.putString("main_page_id", "{page-id}");
params.putString("store_number", "12345");
params.putString("location_page_id", "{subpage-id}");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/locations",
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
  @"main_page_id": @"{page-id}",
  @"store_number": @"12345",
  @"location_page_id": @"{subpage-id}",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/locations"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A page access token is required to update locations on a parent page.

### Fields

To update, include any of the required [publishing fields](#pubfields), and any of [the other publishing fields](#pubfields) that you want to change values for.

### Response

If successful:

```
{
  "success": true
}
```

Otherwise a relevant error message will be returned.
