Graph API Version

[v25.0](#)

# Targeting

## Reading

Targeting result

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `adgroup_id`  id | ID of the ad group  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `age_max`  unsigned int32 | Targeting user maximum age  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `age_min`  unsigned int32 | Targeting user minimum age  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `age_range`  list<unsigned int32> | Suggested targeting user minimum and maximum age range  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `alternate_auto_targeting_option`  string | Alternative Auto Targeting (eg: lal, none)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `app_install_state`  string | Targeting whether an app is installed or not on a device  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `audience_network_positions`  list<enum> | The specified Audience Network positions to which the adset will deliver  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `behaviors`  list<IDName> | Behaviors to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `brand_safety_content_filter_levels`  list<string> | Brand Safety Content Filter levels for contextual placements (Instream Video, Instant Article, Audience Network  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `brand_safety_content_severity_levels`  list<string> | Content Severity levels for Brand Safety placements (Instream Video, Instant Article, Audience Network)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `catalog_based_targeting`  CatalogBasedTargeting | Specs defining how your catalog will be used to target ads  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `cities`  list<IDName> | Targeting cities  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `college_years`  list<unsigned int32> | Targeting user year in college  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `connections`  [list<ConnectionsTargeting>](https://developers.facebook.com/docs/graph-api/reference/connections-targeting/) | Targeting connections  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `contextual_targeting_categories`  list<IDName> | Categories for contextual targeting  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `countries`  list<string> | Targeting countries  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `country`  list<string> | Targeting country  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `country_groups`  list<string> | Targeting groups of countries  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `custom_audiences`  list<RawCustomAudience> | Custom list of users to target to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `device_platforms`  list<enum {mobile, desktop, connected\_tv}> | The user specified device platforms on which the ad set will be delivered  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `direct_install_devices`  bool | Direct Install Devices  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `dynamic_audience_ids`  list<numeric string> | Dynamic audience IDs  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `education_majors`  list<IDName> | Majors during education  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `education_schools`  list<IDName> | Schools attended  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `education_statuses`  list<unsigned int32> | Targeting user education statuses  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `effective_audience_network_positions`  list<enum> | The actual Audience Network positions to which the adset will deliver |
| `effective_brand_safety_content_filter_levels`  list<string> | Read-only. The effective brand safety content filter levels applied to ad delivery, computed as the most conservative merge of account-level and campaign-level settings. Uses the same values as brand\_safety\_content\_filter\_levels. |
| `effective_device_platforms`  list<enum {mobile, desktop, connected\_tv}> | The actual device platforms on which the ad set will be delivered |
| `effective_facebook_positions`  list<enum> | The actual Facebook positions that the adset will be delivered to |
| `effective_instagram_positions`  list<enum> | The actual Instagram positions that the adset will be delivered to |
| `effective_messenger_positions`  list<enum> | The actual Messenger positions that the adset will be delivered to |
| `effective_publisher_platforms`  list<enum> | The actual platforms on which the ad set will be delivered |
| `effective_threads_positions`  list<enum> | The actual Threads positions to which the adset will deliver |
| `effective_whatsapp_positions`  list<enum> | The actual WhatsApp positions to which the adset will deliver |
| `engagement_specs`  list<TargetingDynamicRule> | Engagement activities that people matched based on their online behaviors. e.g. video they watched, pages visited, ads clicked, etc  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `ethnic_affinity`  list<IDName> | Ethnic affinities to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `exclude_reached_since`  list<string> | Exclude users reached by this account since given date  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_brand_safety_content_types`  list<string> | Excluded Brand Safety content types, for example Instream live gaming  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_connections`  [list<ConnectionsTargeting>](https://developers.facebook.com/docs/graph-api/reference/connections-targeting/) | Connections to exclude targeting to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_custom_audiences`  list<RawCustomAudience> | Custom list of users to exclude targeting to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_dynamic_audience_ids`  list<numeric string> | Excluded dynamic audience IDs  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_engagement_specs`  list<TargetingDynamicRule> | Similar to engagement\_specs, but instead of include people who have performed certain activities, target the people who have not performed the specified activities  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_geo_locations`  TargetingGeoLocation | Excluded locations for ads targeting  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_mobile_device_model`  list<string> | Excluded mobile device models  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_product_audience_specs`  list<TargetingProductAudienceSpec> | Similar to product\_audience\_specs, but instead of including the people who have performed certain actions, excluding them  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_publisher_categories`  list<string> | Excluded publisher categories, for example app categories on Audience Network  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_publisher_list_ids`  list<numeric string> | Excluded publisher list IDs on Audience Network  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_user_device`  list<string> | Excluded user mobile devices  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `exclusions`  FlexibleTargeting | Excluded targeting rules and clusters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `facebook_positions`  list<enum> | The specified Facebook positions that the adset will be delivered to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `family_statuses`  list<IDName> | Status of family  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `fb_deal_id`  numeric string | Deal Id for predefined deals between advertisers and publishers (eg: Instant Articles, Video Home, Audience Network)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `flexible_spec`  list<FlexibleTargeting> | Flexible combination of targeting rules and clusters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `friends_of_connections`  [list<ConnectionsTargeting>](https://developers.facebook.com/docs/graph-api/reference/connections-targeting/) | Friends of connections to target to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `genders`  list<unsigned int32> | Targeting genders  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `generation`  list<IDName> | Generations to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `geo_locations`  TargetingGeoLocation | Locations used for ad targeting  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `home_ownership`  list<IDName> | Home owership types to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `home_type`  list<IDName> | Home types to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `home_value`  list<IDName> | Home values to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `household_composition`  list<IDName> | Household compositions to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `income`  list<IDName> | Income to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `industries`  list<IDName> | Industries to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `instagram_positions`  list<enum> | The specified Instagram positions that the adset will be delivered to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `install_state_application`  numeric string | Application to be used for install state exclusion  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `instream_video_skippable_excluded`  bool | The opt-out option for advertisers to opt out from the in-stream skippable ads  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `instream_video_sponsorship_placements`  list<string> | Instream Video placements to target, pre-roll/mid-roll/  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `interested_in`  list<unsigned int32> | Targeting gender of person user is interested in  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `interests`  list<IDName> | Targeting user interests  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_whatsapp_destination_ad`  bool | Targeting users who is eligible for WhatsApp destination ad |
| `keywords`  list<string> | Targeting keywords  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `life_events`  list<IDName> | Events in life  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `locales`  list<unsigned int32> | Targeting user locales  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `messenger_positions`  list<enum> | The specified Messenger positions that the adset will be delivered to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `moms`  list<IDName> | Types of moms to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `net_worth`  list<IDName> | Net worth to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `office_type`  list<IDName> | Office types to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `place_page_set_ids`  list<numeric string> | Targeting a set of locations (local pages) under a main page  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `political_views`  list<unsigned int32> | Targeting user political views  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `politics`  list<IDName> | Politics to target  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `product_audience_specs`  list<TargetingProductAudienceSpec> | A JSON spec that is used to describe the people who have performed certain actions on a set of products  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `prospecting_audience`  TargetingProspectingAudience | Advertiser specified prospecting audience specs  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `publisher_platforms`  list<enum> | The user specified platforms on which the ad set will be delivered  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `radius`  numeric string | Targeting user located within a radius of the location  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `regions`  list<IDName> | Targeting regions  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `relationship_statuses`  list<unsigned int32> | Targeting relationship statuses  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `site_category`  list<string> | The site category |
| `targeting_automation`  TargetingAutomation | targeting\_automation  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `targeting_optimization`  string | Relax targeting constraints to hints  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `targeting_relaxation_types`  TargetingRelaxation | Allow passing of multiple targeting relaxations via a map  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `threads_positions`  list<enum> | The specified Threads positions to which the adset will deliver  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_adclusters`  list<IDName> | Targeting user ad clusters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_age_unknown`  bool | Advertiser selects to target users whose age is unknown  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_device`  list<string> | User mobile device  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_event`  list<unsigned int32> | User event  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_os`  list<string> | User mobile OS  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `whatsapp_positions`  list<enum> | The specified WhatsApp positions to which the adset will deliver  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `wireless_carrier`  list<string> | The wireless carrier  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `work_employers`  list<IDName> | Employers  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `work_positions`  list<IDName> | Positions at work  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `zips`  list<string> | Targeting locations' zip codes  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
