package com.vinsguru.user.controller;

import com.vinsguru.user.dto.TitleDto;
import com.vinsguru.user.dto.UserDto;
import com.vinsguru.user.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(UserController.class)
class UserControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private UserService userService;

    @Test
    void getUser_returnsCompositeWhenPresent() throws Exception {
        var dto = new UserDto(1, "Alice Adams", "alice@traceflix.test", "PREMIUM", "PREMIUM",
                List.of(new TitleDto(7, "Fight Club", "Drama", 1999, 8.8)));
        when(userService.getUser(1)).thenReturn(Optional.of(dto));

        mockMvc.perform(get("/api/users/1"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.name").value("Alice Adams"))
               .andExpect(jsonPath("$.role").value("PREMIUM"))
               .andExpect(jsonPath("$.recommendations[0].name").value("Fight Club"));
    }

    @Test
    void getUser_returns404WhenMissing() throws Exception {
        when(userService.getUser(99)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/users/99"))
               .andExpect(status().isNotFound());
    }

}
