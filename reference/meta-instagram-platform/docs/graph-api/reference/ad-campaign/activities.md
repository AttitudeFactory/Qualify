Graph API Version

[v25.0](#)

# Ad Set Activities

## Reading

### Event type descriptions

Here is a list of `event_type` by object:

**Ad account related event**

Name | Description || ad\_account\_update\_spend\_limit | update the spend limit of an ad account |
| ad\_account\_reset\_spend\_limit | reset the spend limit of an ad account. |
| ad\_account\_remove\_spend\_limit | remove the spend limit of an ad account. You would have unlimited spend limit if you remove spend limit |
| ad\_account\_set\_business\_information | set business information for this ad account. |
| ad\_account\_update\_status | update account status, includes: disabled, active, test, unsettled, pending closure, closed, pending risk review, in grace period |
| ad\_account\_add\_user\_to\_role | add user to ad account |
| ad\_account\_remove\_user\_from\_role | remove user from ad account |
| add\_images | add an image to ad account image library |
| edit\_images | edit an image in ad account image library |

**Billing related event**

Name | Description || ad\_account\_billing\_charge | charge ad account |
| ad\_account\_billing\_charge\_back | undo the charging on ad account per bank's instructions |
| ad\_account\_billing\_charge\_back\_reversal | reapply the undone charging |
| ad\_account\_billing\_decline | billings was declined |
| ad\_account\_billing\_refund | refund on ad account |
| add\_funding\_source | add funding source to ad account |
| remove\_funding\_source | remove funding source from ad account |

**Campaign related event**

Name | Description || create\_campaign | create campaign |
| update\_campaign\_name | update campaign friendly name |
| update\_campaign\_run\_status | update campaign run status |

**Ad set related event**

Name | Description || create\_ad\_set | create ad set |
| update\_ad\_set\_bidding | update bid information |
| update\_ad\_set\_target\_spec | update ad set targeting |
| update\_ad\_set\_name | update ad set friendly name |
| update\_ad\_set\_run\_status | update ad set run status |
| update\_ad\_set\_budget | update ad set budget |
| update\_ad\_set\_duration | update ad set duration |

**Adgroup related event**

Name | Description || create\_ad | create ad |
| update\_ad\_creative | update creative of ad, including image/title/text change. |
| update\_ad\_run\_status | update adgroup run status |
| update\_ad\_friendly\_name | update adgroup friendly name |
| ad\_review\_approved | ad review was approved |
| ad\_review\_declined | ad review was not approved |

**Other**

Name | Description || create\_audience | create custom audience |
| delete\_audience | delete custom audience |

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `after`  string | after |
| `business_id`  numeric string or integer | This parameter is a required parameter once the ad account is associated with any business account. |
| `category`  enum {ACCOUNT, AD, AD\_KEYWORDS, AD\_SET, AUDIENCE, BID, BUDGET, CAMPAIGN, DATE, STATUS, TARGETING} | Filter events by category. |
| `limit`  integer | limit |
| `since`  datetime | The start time to query account history. Default is 7 days prior. |
| `uid`  int | Filter events by the user id. |
| `until`  datetime | The end time to query account history. Default is now. |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [AdActivity](/docs/marketing-api/reference/ad-activity/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 190 | Invalid OAuth 2.0 Access Token |
| 100 | Invalid parameter |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
