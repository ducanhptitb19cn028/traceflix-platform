package com.vinsguru.user.service;

import com.vinsguru.user.client.AuthClient;
import com.vinsguru.user.client.RecommendationClient;
import com.vinsguru.user.dto.AccountDto;
import com.vinsguru.user.dto.TitleDto;
import com.vinsguru.user.dto.UserDto;
import com.vinsguru.user.entity.Profile;
import com.vinsguru.user.repository.ProfileRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @Mock
    private ProfileRepository repository;
    @Mock
    private AuthClient authClient;
    @Mock
    private RecommendationClient recommendationClient;

    @InjectMocks
    private UserService service;

    private static Profile profile(int id) {
        var p = new Profile();
        p.setId(id);
        p.setName("Alice Adams");
        p.setEmail("alice@traceflix.test");
        p.setTier("PREMIUM");
        return p;
    }

    @Test
    void getUser_composesProfileWithRoleAndRecommendations() {
        when(repository.findById(1)).thenReturn(Optional.of(profile(1)));
        when(authClient.getAccount(1)).thenReturn(new AccountDto(1, "alice", "PREMIUM"));
        when(recommendationClient.getRecommendations(1))
                .thenReturn(List.of(new TitleDto(7, "Fight Club", "Drama", 1999, 8.8)));

        Optional<UserDto> result = service.getUser(1);

        assertThat(result).isPresent();
        UserDto dto = result.get();
        assertThat(dto.name()).isEqualTo("Alice Adams");
        assertThat(dto.tier()).isEqualTo("PREMIUM");
        assertThat(dto.role()).isEqualTo("PREMIUM");                 // from auth
        assertThat(dto.recommendations()).extracting(TitleDto::name) // from recommendation
                                         .containsExactly("Fight Club");
    }

    @Test
    void getUser_rolesFallBackToUnknownWhenAuthReturnsNull() {
        when(repository.findById(1)).thenReturn(Optional.of(profile(1)));
        when(authClient.getAccount(1)).thenReturn(null);
        when(recommendationClient.getRecommendations(1)).thenReturn(List.of());

        UserDto dto = service.getUser(1).orElseThrow();

        assertThat(dto.role()).isEqualTo("UNKNOWN");
        assertThat(dto.recommendations()).isEmpty();
    }

    @Test
    void getUser_emptyWhenProfileMissing_noDownstreamCalls() {
        when(repository.findById(99)).thenReturn(Optional.empty());
        // downstream clients must not be required when the profile is absent
        lenient().when(authClient.getAccount(99)).thenReturn(null);

        assertThat(service.getUser(99)).isEmpty();
    }

}
