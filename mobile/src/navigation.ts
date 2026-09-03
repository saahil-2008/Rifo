import { createNavigationContainerRef } from '@react-navigation/native';

/** Route map for the app's single native stack (FR-9: four screens). */
export type RootStackParamList = {
  Onboarding: undefined;
  History: undefined;
  Detail: { claimId?: number } | undefined;
  Settings: undefined;
};

export const navRef = createNavigationContainerRef<RootStackParamList>();

/** Navigate from outside a screen component (e.g. a bubble tap). */
export function navigateTo<RouteName extends keyof RootStackParamList>(
  name: RouteName,
  params?: RootStackParamList[RouteName],
): void {
  if (navRef.isReady()) {
    navRef.navigate(name as never, params as never);
  }
}
