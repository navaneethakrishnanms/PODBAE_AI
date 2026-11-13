import { Route, Switch } from 'wouter';
import Admin, { AdminSetup } from './pages/Admin';
import AdminLabels from './pages/AdminLabels';
import AdminPairLabels from './pages/AdminPairLabels';
import AdvertiserSubmit from './pages/AdvertiserSubmit';
import { Login } from './pages/Auth';
import CampaignBuilder from './pages/CampaignBuilder';
import Dashboard from './pages/Dashboard';
import Discover from './pages/Discover';
import { GetStarted, GuestSubmit, Onboarding, PodcasterSubmit, Success, VenueSubmit } from './pages/Intake';
import Intelligence from './pages/Intelligence';
import Landing from './pages/Landing';
import Messages from './pages/Messages';
import { Analytics, Enterprise, Listen, PartnershipSignup, Partners, Schedule } from './pages/Misc';
import { Embed, ProfileEdit, PublicProfile } from './pages/Profile';
import MockCheckout from './pages/MockCheckout';
import Swipe from './pages/Swipe';

export default function App() {
  return (
    <Switch>
      <Route path="/" component={Landing} />
      <Route path="/get-started" component={GetStarted} />
      <Route path="/submit" component={PodcasterSubmit} />
      <Route path="/advertiser-submit" component={AdvertiserSubmit} />
      <Route path="/venue-submit" component={VenueSubmit} />
      <Route path="/guest-submit" component={GuestSubmit} />
      <Route path="/login" component={Login} />
      <Route path="/onboarding" component={Onboarding} />
      <Route path="/success" component={Success} />

      <Route path="/member-dashboard" component={Dashboard} />
      <Route path="/dashboard" component={Dashboard} />
      <Route path="/member" component={Dashboard} />
      <Route path="/dashboard/campaign-builder" component={CampaignBuilder} />

      <Route path="/matching" component={Swipe} />
      <Route path="/mymatches" component={Swipe} />
      <Route path="/swipe" component={Swipe} />

      <Route path="/discover" component={Discover} />
      <Route path="/p/:userId" component={PublicProfile} />
      <Route path="/profile/:userId" component={PublicProfile} />
      <Route path="/embed/:userId" component={Embed} />
      <Route path="/profile" component={ProfileEdit} />

      <Route path="/intelligence" component={Intelligence} />
      <Route path="/messages" component={Messages} />
      <Route path="/schedule" component={Schedule} />
      <Route path="/analytics" component={Analytics} />
      <Route path="/partners" component={Partners} />
      <Route path="/listen" component={Listen} />
      <Route path="/listener-recommendations" component={Listen} />
      <Route path="/enterprise" component={Enterprise} />
      <Route path="/partnership-signup" component={PartnershipSignup} />

      <Route path="/mock-checkout" component={MockCheckout} />

      <Route path="/admin/setup" component={AdminSetup} />
      <Route path="/admin/labels/pairs" component={AdminPairLabels} />
      <Route path="/admin/labels" component={AdminLabels} />
      <Route path="/admin" component={Admin} />
      <Route>
        <div className="p-20 text-center text-xl">Page not found. <a className="text-primary" href="/">Go home</a></div>
      </Route>
    </Switch>
  );
}
