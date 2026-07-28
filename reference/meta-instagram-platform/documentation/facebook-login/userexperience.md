# User Experience Design



The onboarding experience is one of the most important user experiences in your app. A high quality onboarding experience can lead to conversion rates above 90% and encourages people to become more engaged and profitable.

Facebook Login lets people start using your app quickly and easily, and enjoy more personalized and meaningful experiences. In this doc, we offer tips and considerations to create a great login user experience with Facebook Login.

1. [Show value first](#showvaluefirst)
2. [Avoid unnecessary steps](#avoidunnecessarysteps)
3. [Button design](#buttondesign)
4. [Permissions](#permissions)
5. [Provide a way to log out](#loggingout)
6. [Test and measure](#testing)

## 1. Show value before prompting people to login &#123;#showvaluefirst&#125;

When deciding where in the user experience to prompt people to log in, ask yourself at what point will people appreciate what your app has to offer enough to trust it with their information.

This is often influenced by what people experience before even downloading the app, but there is a lot you can do to further influence this by design within the app.

Here are a few design approaches to encourage more people to log in:

* Provide a clear and succinct statement of what your app has to offer
* Provide a glimpse of the content they’ll get after they&#039;re logged in
* Provide a new user experience
* Allow people to experience your app without an account

### Provide a clear and succinct statement of what your app has to offer

Provide a clear, succinct and compelling statement about what your app has to offer. It might have been a while since they downloaded the app or read about it in the app store.

### Provide a glimpse of the content they’ll get after they log in

Provide a glimpse of the content available to people prior to logging in, like the background photo in this example. It doesn&#039;t have to be detailed, even blurred out images of Pinterest&#039;s pinboard encourages more people to log into Pinterest.

### Provide a new user experience

If your app requires additional education to have the best experience, include a multi step demo above your Login button. This gives people the option to either learn more or log in immediately if they&#039;re ready.

### Allow people to experience your app before logging in

If possible, allow people experience your app before prompting them to log in. For example, many ecommerce apps such as Zulily don&#039;t require people to log in until they&#039;re ready to check out.

## 2. Avoid unnecessary steps &#123;#avoidunnecessarysteps&#125;

Reducing unnecessary steps is one of the most effective ways to improve your conversion rate.

Avoid asking users to first tap “Login” or “Register” to get to the Facebook login button. With Facebook Login, this is an unnecessary step. There’s no need for people to even have stop to think about if they have an account or not.

In addition, after people have logged in with Facebook, don&#039;t prompt them to create a username or password. One of the most popular reasons people log in with Facebook is because “it’s fast and easy and I don’t have to enter a password”. After logging in with Facebook, people especially do not want to have to create a username or password.

## 3. Button design &#123;#buttondesign&#125;

### Logo

In order to build recognition and trust, always use the [approved “f” Logo](https://en.facebookbrand.com/assets/f-logo/?audience=advertisers) available on the [Facebook Brand Resource Center](https://www.facebookbrand.com).

When using the “f” Logo in the login button design, it should appear before the call to action. Don’t use it as part of the call to action by saying “Login with “f” Logo.

### Color

Color is one of the best ways for people to recognize something quickly. From a usability perspective, the more quickly people recognize what your button is and does, the faster they want to tap on it and the more seamless the experience.

Button colors are white and Facebook blue: 5890FF. Around the world, when people talk about Facebook Login they often refer to it as &quot;the blue button&quot;. If you are unable to use Facebook blue,  revert to black and white.

**FACEBOOK BLUE COLOR VALUES**

* CMYK Coated: 83 / 52 / 00 / 00
* CMYK Uncoated: 77 / 36 / 00 / 00
* PMS 2727C
* PMS 2382U
* Hex #1877F2
* R = 24 G = 119 B = 242

### Text

The preferred labels are either &quot;Continue with Facebook&quot; or &quot;Login with Facebook&quot; depending on the context. When using the [“f” Logo](https://en.facebookbrand.com/assets/f-logo/?audience=advertisers) with a call to action, use the official version available for download on the Facebook [Facebook Brand Resource Center](https://www.facebookbrand.com).

Place the call to action copy within the login button, it should not be outside of the button.

Choose the font, font weight, and kerning that looks best in your app, but optimize for easy legibility.

### Placement

Your login button should be as fast and easy to recognize and tap as possible. On a mobile device, this means close to the thumb and large enough to tap easily. It’s simplistic but true; larger buttons convert better than small buttons.

The “f” Logo is provided in various sizes for button scaling purposes, but the proportions and typography style must stay consistent.

### Do&#039;s and Dont&#039;ts

*  **DO** use the approved [“f” Logo](https://en.facebookbrand.com/assets/f-logo/?audience=advertisers) provided on the Facebook [Facebook Brand Resource Center](https://www.facebookbrand.com) and follow the guidelines for use.

* **DO** use the preferred label &quot;Continue with Facebook&quot; or &quot;Login with Facebook&quot; on the login button depending on the context, and ensure the copy resides inside the button design.

* **DON’T** modify the &quot;f&quot; logo in any way, such as by changing the design, scale, color or any other custom variation. If you can’t use the correct color due to technical limitations, use black and white.

* **DON’T** use the “f” logo on a button without an appropriate call to action, preferably &quot;Continue with Facebook&quot; or &quot;Login with Facebook&quot;

* **DON’T** place the call to action copy (example: Continue with Facebook) outside of the login button.

## 4. Permissions &#123;#permissions&#125;

### Only ask for the permissions you need

The fewer permissions you ask for, the easier it is for people to feel comfortable granting them. We&#039;ve seen that asking for fewer permissions typically results in greater conversion.

You can always ask for additional permissions later after people have had a chance to try out your app.

An additional benefit of asking for fewer permissions is that you might not need to submit your app for [Login Review](https://developers.facebook.com/docs/facebook-login/review). You only need to submit for Login Review if you&#039;re requesting permissions other than `public_profile` and `email`.

### Ask for permissions in context and explain why

People are most likely to accept permission requests when they understand why your app needs that information to offer a better experience. So trigger permission requests when people are trying to accomplish an action in your app which requires that specific permission.

For example, the Facebook app only asks for Location Services when people explicitly tap on the location button when updating their status.

## 5. Provide a way to log out &#123;#loggingout&#125;

Once people are logged in, you also need to give them a way to log out, disconnect their account, or delete it all together. In addition to being a courtesy, this is also a requirement of our [Developer Policies for Login](https://developers.facebook.com/devpolicy/#login).

The dating app Tinder, for example, gives you the option to hide your profile card to prevent people from finding you, log out, or delete your account entirely.

## 6. Test and measure &#123;#testing&#125;

Not even the best designers get their onboarding flow right on the first try. Great onboarding experiences are usually the result of thoughtful design and testing, with multiple iterations.

Before launching your app, run a qualitative usability test to understand how people are reacting to what they see. It doesn&#039;t have to be formal to be useful, but make sure to watch people run through the experience.

In addition to qualitative testing, use analytics to understand if people are completing the process and their overall conversion rates. Best practice apps can see conversion rates of over 90%.
