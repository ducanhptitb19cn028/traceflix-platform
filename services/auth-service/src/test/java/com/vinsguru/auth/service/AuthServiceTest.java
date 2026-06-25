package com.vinsguru.auth.service;

import com.vinsguru.auth.dto.AccountDto;
import com.vinsguru.auth.dto.AuthResult;
import com.vinsguru.auth.entity.Account;
import com.vinsguru.auth.repository.AccountRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock
    private AccountRepository repository;

    @InjectMocks
    private AuthService service;

    private static Account account(int id, String username, String role, String token) {
        var a = new Account();
        a.setId(id);
        a.setUsername(username);
        a.setRole(role);
        a.setToken(token);
        return a;
    }

    @Test
    void validate_knownTokenIsValidWithRole() {
        when(repository.findByToken("tok-alice"))
                .thenReturn(Optional.of(account(1, "alice", "PREMIUM", "tok-alice")));

        AuthResult result = service.validate("tok-alice");

        assertThat(result.valid()).isTrue();
        assertThat(result.username()).isEqualTo("alice");
        assertThat(result.role()).isEqualTo("PREMIUM");
    }

    @Test
    void validate_unknownTokenIsInvalid() {
        when(repository.findByToken("nope")).thenReturn(Optional.empty());

        AuthResult result = service.validate("nope");

        assertThat(result.valid()).isFalse();
        assertThat(result.role()).isNull();
    }

    @Test
    void getAccount_returnsDtoWithoutToken() {
        when(repository.findById(2))
                .thenReturn(Optional.of(account(2, "bob", "STANDARD", "tok-bob")));

        Optional<AccountDto> result = service.getAccount(2);

        assertThat(result).isPresent();
        assertThat(result.get().username()).isEqualTo("bob");
        assertThat(result.get().role()).isEqualTo("STANDARD");
    }

    @Test
    void getAccount_emptyWhenMissing() {
        when(repository.findById(99)).thenReturn(Optional.empty());

        assertThat(service.getAccount(99)).isEmpty();
    }

}
