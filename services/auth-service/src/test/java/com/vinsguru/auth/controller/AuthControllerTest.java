package com.vinsguru.auth.controller;

import com.vinsguru.auth.dto.AccountDto;
import com.vinsguru.auth.dto.AuthResult;
import com.vinsguru.auth.service.AuthService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(AuthController.class)
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private AuthService authService;

    @Test
    void validate_returnsResult() throws Exception {
        when(authService.validate("tok-alice"))
                .thenReturn(new AuthResult(true, "alice", "PREMIUM"));

        mockMvc.perform(get("/api/auth/validate").param("token", "tok-alice"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.valid").value(true))
               .andExpect(jsonPath("$.role").value("PREMIUM"));
    }

    @Test
    void validate_invalidToken() throws Exception {
        when(authService.validate("nope")).thenReturn(AuthResult.invalid());

        mockMvc.perform(get("/api/auth/validate").param("token", "nope"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.valid").value(false));
    }

    @Test
    void account_returnsWhenPresent() throws Exception {
        when(authService.getAccount(2))
                .thenReturn(Optional.of(new AccountDto(2, "bob", "STANDARD")));

        mockMvc.perform(get("/api/auth/2"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.username").value("bob"));
    }

    @Test
    void account_returns404WhenMissing() throws Exception {
        when(authService.getAccount(99)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/auth/99"))
               .andExpect(status().isNotFound());
    }

}
